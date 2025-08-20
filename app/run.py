from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

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


def extract_forward_info(msg) -> Tuple[bool, Optional[int], Optional[int], Optional[str]]:
    """
    메시지가 forward된 것인지 확인하고 원본 정보를 추출
    
    Returns:
        Tuple[is_forward, original_chat_id, original_message_id, original_text]
    """
    # Telethon에서 forward 정보 확인
    if hasattr(msg, 'forward') and msg.forward:
        # Forward된 메시지인 경우
        original_chat_id = None
        original_message_id = None
        original_text = None
        
        # 원본 채널/채팅 정보 추출
        if hasattr(msg.forward, 'chat_id'):
            original_chat_id = msg.forward.chat_id
        elif hasattr(msg.forward, 'channel_id'):
            original_chat_id = msg.forward.channel_id
        elif hasattr(msg.forward, 'user_id'):
            original_chat_id = msg.forward.user_id
            
        # 원본 메시지 ID 추출
        if hasattr(msg.forward, 'id'):
            original_message_id = msg.forward.id
            
        # 원본 텍스트는 현재 메시지의 텍스트 사용 (forward 시 텍스트가 복사됨)
        original_text = getattr(msg, 'message', '')
        
        return True, original_chat_id, original_message_id, original_text
    
    return False, None, None, None


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

        # Use event.chat_id directly; event.chat can be None depending on cache/state
        chat_id = getattr(event, "chat_id", None) or getattr(getattr(event, "chat", None), "id", None)
        if chat_id is None:
            mlog.warning("Missing chat_id on event; dropping")
            return

        # Log non-text messages as well
        if not getattr(msg, "message", "").strip():
            meta = channel_cache.get(chat_id) or {}
            mlog.info(
                f"수신 메시지(비텍스트): {meta.get('title','Unknown')} ({meta.get('username') or chat_id}) "
                f"msg_id={msg.id}"
            )
            return

        # Forward 메시지 확인 및 원본 정보 추출
        is_forward, original_chat_id, original_message_id, original_text = extract_forward_info(msg)
        
        # Forward된 메시지인 경우 원본 텍스트 사용, 아니면 현재 텍스트 사용
        if is_forward and original_text:
            text = normalize_text(original_text)
            mlog.info(f"Forward 메시지 감지: 원본 chat_id={original_chat_id}, msg_id={original_message_id}")
        else:
            text = normalize_text(msg.message)
        
        meta = channel_cache.get(chat_id) or {}
        snippet = text[:200] + ("…" if len(text) > 200 else "")
        
        # Forward 여부를 로그에 포함
        forward_info = " [FORWARD]" if is_forward else ""
        mlog.info(
            f"수신 메시지{forward_info}: {meta.get('title','Unknown')} ({meta.get('username') or chat_id}) "
            f"msg_id={msg.id}, len={len(text)} | {snippet}"
        )
        
        sim = compute_simhash(text)

        now_ts = int(datetime.utcnow().timestamp())
        since_ts = now_ts - settings.dedup_recent_minutes * 60
        
        # Forward된 메시지인 경우 원본 메시지 ID로 중복 체크
        check_message_id = original_message_id if is_forward and original_message_id else msg.id
        check_chat_id = original_chat_id if is_forward and original_chat_id else chat_id
        
        similar = store.find_recent_similar(sim, since_ts, settings.dedup_hamming_threshold)
        if similar:
            similar_chat_id, similar_msg_id, _ = similar
            mlog.info(f"Duplicate dropped (current: chat_id={chat_id}, msg_id={msg.id}, check: chat_id={check_chat_id}, msg_id={check_message_id})")
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

        # Forward된 메시지의 경우 원본 링크 생성
        if is_forward and original_chat_id and original_message_id:
            # 원본 채널 메타데이터 가져오기 (캐시에서 찾거나 새로 생성)
            original_meta = channel_cache.get(original_chat_id)
            if not original_meta:
                try:
                    # 원본 채널 정보를 가져와서 캐시에 저장
                    original_entity = await tg.client.get_entity(original_chat_id)
                    original_meta = {
                        "title": getattr(original_entity, "title", f"Channel {original_chat_id}"),
                        "username": getattr(original_entity, "username", None),
                        "is_public": bool(getattr(original_entity, "username", None)),
                        "internal_id": None
                    }
                    if not original_meta["is_public"]:
                        # 비공개 채널의 경우 internal_id 계산
                        from telethon import utils
                        peer_id = utils.get_peer_id(original_entity)
                        if isinstance(peer_id, int):
                            peer_abs = abs(peer_id)
                            s = str(peer_abs)
                            if s.startswith("100"):
                                original_meta["internal_id"] = int(s[3:])
                    channel_cache[original_chat_id] = original_meta
                except Exception as e:
                    mlog.warning(f"원본 채널 정보 가져오기 실패: {e}")
                    original_meta = {"title": f"Unknown Channel {original_chat_id}", "username": None, "is_public": False, "internal_id": None}
            
            # 원본 메시지 링크 생성
            orig_link = build_original_link(
                chat_id=original_chat_id,
                message_id=original_message_id,
                is_public=bool(original_meta.get("is_public")),
                username=original_meta.get("username"),
                internal_id=original_meta.get("internal_id"),
            )
            source_title = original_meta.get("title", f"Unknown Channel {original_chat_id}")
        else:
            # 일반 메시지의 경우 현재 채널 링크 사용
            meta = channel_cache.get(chat_id) or {}
            orig_link = build_original_link(
                chat_id=chat_id,
                message_id=message_id,
                is_public=bool(meta.get("is_public")),
                username=meta.get("username"),
                internal_id=meta.get("internal_id"),
            )
            source_title = meta.get("title", "Unknown")

        # Importance thresholding
        if IMPORTANCE_ORDER.get(analysis.importance, 0) < IMPORTANCE_ORDER.get(
            settings.important_threshold, 1
        ):
            # Store analysis but do not forward
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
        html = format_html(
            source_title=source_title,
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
        forward_log = f" [FORWARD from {original_chat_id}:{original_message_id}]" if is_forward else ""
        mlog.info(f"Forwarded message (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance}){forward_log}")

    tg.on_new_message(handle_message, chats=None)
    logger.info("Listening... (Ctrl+C to stop)")
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())


