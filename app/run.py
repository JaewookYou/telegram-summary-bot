from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.config import load_settings
from app.dedup import compute_simhash, normalize_text
from app.formatter import build_original_link, format_html
from app.llm import OpenAILLM
from app.storage import SQLiteStore
from app.telegram_client import TG
from app.logging_utils import setup_logging
from app.rules import boost_importance_for_events

import logging
import sqlite3
import os


IMPORTANCE_ORDER = {"low": 0, "medium": 1, "high": 2}


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("app")
    logger.info("Starting telegram-summary-bot")

    settings = load_settings()
    if settings.telegram_api_id == 0 or not settings.telegram_api_hash:
        logger.error("Missing TELEGRAM_API_ID/HASH")
        raise RuntimeError("TELEGRAM_API_ID/HASH가 필요합니다. .env를 설정하세요.")
    if not settings.source_channels:
        logger.error("SOURCE_CHANNELS is empty")
        raise RuntimeError("SOURCE_CHANNELS가 비어 있습니다.")

    store = SQLiteStore(settings.sqlite_path)
    if not settings.openai_api_key:
        logger.error("Missing OPENAI_API_KEY")
        raise RuntimeError("OPENAI_API_KEY가 필요합니다. .env를 설정하세요.")
    llm = OpenAILLM(settings.openai_api_key, settings.openai_model)
    tg = TG(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash)
    try:
        await tg.start()
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            logger.error(
                "Telethon 세션 DB가 잠겨 있습니다. 다른 프로세스가 같은 세션을 사용 중일 수 있습니다.\n"
                f"세션 파일: {settings.telegram_session}.session\n"
                "조치: (1) 다른 실행 중인 봇/스크립트 종료, (2) 세션 파일을 새 이름으로 변경 후 TELEGRAM_SESSION 변경,\n"
                "또는 (3) *.session-journal 임시 파일 삭제 후 재시도"
            )
        raise

    channel_cache: Dict[int, dict] = {}

    async def ensure_channel_meta(identifier: str) -> dict:
        meta = await tg.iter_channel_meta(identifier)
        return {
            "chat_id": meta.chat_id,
            "title": meta.title,
            "username": meta.username,
            "internal_id": meta.internal_id,
            "is_public": meta.is_public,
        }

    # Preload source channel metas
    chat_filters = []
    for src in settings.source_channels:
        meta = await ensure_channel_meta(src)
        channel_cache[meta["chat_id"]] = meta
        chat_filters.append(meta["chat_id"])  # restrict events to known channels
        logger.info(f"Listening source: {meta['title']} ({meta['username'] or meta['chat_id']})")

    logger.info(
        "Aggregator=%s, importance>=%s, dedup_window=%sm, hamming<=%s",
        settings.aggregator_channel,
        settings.important_threshold,
        settings.dedup_recent_minutes,
        settings.dedup_hamming_threshold,
    )

    async def handle_message(event):
        mlog = logging.getLogger("app.msg")
        msg = event.message
        if not getattr(msg, "message", "").strip():
            mlog.debug("Skip non-text message")
            return

        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            mlog.debug("Missing chat_id")
            return

        text = normalize_text(msg.message)
        meta = channel_cache.get(chat_id) or {}
        snippet = text[:200] + ("…" if len(text) > 200 else "")
        mlog.info(
            f"수신 메시지: {meta.get('title','Unknown')} ({meta.get('username') or chat_id}) "
            f"msg_id={msg.id}, len={len(text)} | {snippet}"
        )
        sim = compute_simhash(text)

        now_ts = int(datetime.utcnow().timestamp())
        since_ts = now_ts - settings.dedup_recent_minutes * 60
        similar = store.find_recent_similar(sim, since_ts, settings.dedup_hamming_threshold)
        if similar:
            mlog.info(f"Duplicate dropped (chat_id={chat_id}, msg_id={msg.id})")
            return  # duplicate

        # Insert preliminary record
        message_id = msg.id
        author = None
        store.insert_message(
            chat_id=chat_id,
            message_id=message_id,
            date_ts=now_ts,
            author=author,
            text=text,
            simhash_value=sim,
        )

        # LLM analysis
        try:
            analysis = llm.analyze(text)
        except Exception as e:
            logging.getLogger("app.llm").exception("LLM analyze failed")
            return

        # Rule-based importance boost (e.g., giveaways/events)
        boosted_importance, extra_cats, extra_tags = boost_importance_for_events(text, analysis.importance)
        if extra_cats:
            for c in extra_cats:
                if c not in analysis.categories:
                    analysis.categories.append(c)
        if extra_tags:
            for t in extra_tags:
                if t not in analysis.tags:
                    analysis.tags.append(t)
        if boosted_importance != analysis.importance:
            logging.getLogger("app.rules").info(
                f"Importance boosted: {analysis.importance} -> {boosted_importance}"
            )
        analysis.importance = boosted_importance

        # Importance thresholding
        if IMPORTANCE_ORDER.get(analysis.importance, 0) < IMPORTANCE_ORDER.get(
            settings.important_threshold, 1
        ):
            # Store analysis but do not forward
            meta = channel_cache.get(chat_id) or {}
            orig_link = build_original_link(
                chat_id=chat_id,
                message_id=message_id,
                is_public=bool(meta.get("is_public")),
                username=meta.get("username"),
                internal_id=meta.get("internal_id"),
            )
            store.update_analysis(
                chat_id=chat_id,
                message_id=message_id,
                importance=analysis.importance,
                categories=",".join(analysis.categories),
                tags=",".join(analysis.tags),
                summary=analysis.summary,
                original_link=orig_link,
            )
            mlog.info(f"Stored low-priority analysis (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance})")
            return

        # Forward to aggregator channel
        meta = channel_cache.get(chat_id) or {}
        orig_link = build_original_link(
            chat_id=chat_id,
            message_id=message_id,
            is_public=bool(meta.get("is_public")),
            username=meta.get("username"),
            internal_id=meta.get("internal_id"),
        )
        html = format_html(
            source_title=meta.get("title", "Unknown"),
            summary=analysis.summary,
            importance=analysis.importance,
            categories=analysis.categories,
            tags=analysis.tags,
            original_link=orig_link,
        )
        try:
            await tg.send_html(settings.aggregator_channel, html)
        except Exception:
            logging.getLogger("app.tg").exception("Failed to send message to aggregator")
            return

        # Update DB
        store.update_analysis(
            chat_id=chat_id,
            message_id=message_id,
            importance=analysis.importance,
            categories=",".join(analysis.categories),
            tags=",".join(analysis.tags),
            summary=analysis.summary,
            original_link=orig_link,
        )
        mlog.info(f"Forwarded message (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance})")

    tg.on_new_message(handle_message, chats=chat_filters)
    logger.info("Listening... (Ctrl+C to stop)")
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())


