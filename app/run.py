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
from app.image_processor import ImageProcessor
from app.link_processor import LinkProcessor

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
        
        # Forward 객체 정보 로깅 (디버깅용)
        mlog = logging.getLogger("app.msg")
        mlog.info(f"Forward 객체 타입: {type(msg.forward)}")
        mlog.info(f"Forward 객체 속성: {[attr for attr in dir(msg.forward) if not attr.startswith('_')]}")
        
        # 원본 채널/채팅 정보 추출
        if hasattr(msg.forward, 'chat_id'):
            original_chat_id = msg.forward.chat_id
        elif hasattr(msg.forward, 'channel_id'):
            original_chat_id = msg.forward.channel_id
        elif hasattr(msg.forward, 'user_id'):
            original_chat_id = msg.forward.user_id
        elif hasattr(msg.forward, 'from_id'):
            # MessageFwdHeader의 경우
            from_id = msg.forward.from_id
            if hasattr(from_id, 'channel_id'):
                original_chat_id = from_id.channel_id
            elif hasattr(from_id, 'user_id'):
                original_chat_id = from_id.user_id
            elif hasattr(from_id, 'chat_id'):
                original_chat_id = from_id.chat_id
            
        # 원본 메시지 ID 추출
        if hasattr(msg.forward, 'id'):
            original_message_id = msg.forward.id
        elif hasattr(msg.forward, 'channel_post'):
            original_message_id = msg.forward.channel_post
            
        # 원본 텍스트는 현재 메시지의 텍스트 사용 (forward 시 텍스트가 복사됨)
        original_text = getattr(msg, 'message', '')
        
        mlog.info(f"Forward 감지됨 - chat_id={original_chat_id}, msg_id={original_message_id}")
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
    
    # 이미지 및 링크 처리기 초기화
    image_processor = ImageProcessor()
    link_processor = LinkProcessor()
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

    async def get_channel_meta(chat_id: int) -> dict:
        """채널 메타데이터를 가져오거나 캐시에서 찾기"""
        if chat_id in channel_cache:
            return channel_cache[chat_id]
        
        try:
            # 채널 엔티티를 직접 가져와서 메타데이터 생성
            entity = await tg.client.get_entity(chat_id)
            meta = {
                "chat_id": chat_id,
                "title": getattr(entity, "title", f"Channel {chat_id}"),
                "username": getattr(entity, "username", None),
                "internal_id": None,
                "is_public": bool(getattr(entity, "username", None)),
            }
            
            # 비공개 채널의 경우 internal_id 계산
            if not meta["is_public"]:
                from telethon import utils
                peer_id = utils.get_peer_id(entity)
                if isinstance(peer_id, int):
                    peer_abs = abs(peer_id)
                    s = str(peer_abs)
                    if s.startswith("100"):
                        meta["internal_id"] = int(s[3:])
            
            channel_cache[chat_id] = meta
            logger.info(f"채널 메타데이터 캐시 저장: {meta}")
            return meta
        except Exception as e:
            logger.warning(f"채널 메타데이터 가져오기 실패 (chat_id={chat_id}): {e}")
            # 기본 메타데이터 반환
            meta = {
                "chat_id": chat_id,
                "title": f"Unknown Channel {chat_id}",
                "username": None,
                "internal_id": None,
                "is_public": False,
            }
            channel_cache[chat_id] = meta
            return meta

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

        # 채널 필터링: chat_id가 -100으로 시작하는 경우만 채널
        if not str(chat_id).startswith("-100"):
            mlog.info(f"채팅방 메시지 무시: chat_id={chat_id} (채널만 모니터링)")
            return

        # 소스 채널 필터링: 설정된 채널만 처리
        if chat_id not in chat_filters:
            meta = channel_cache.get(chat_id) or {}
            mlog.info(f"미모니터링 채널 메시지: {meta.get('title', 'Unknown')} (chat_id={chat_id})")
            return

        # 메시지 내용 분석
        message_text = getattr(msg, "message", "").strip()
        has_text = bool(message_text)
        has_media = bool(msg.media)
        
        # 모든 수신 메시지 로깅 (INFO 레벨)
        meta = channel_cache.get(chat_id) or {}
        mlog.info(
            f"수신 메시지: {meta.get('title','Unknown')} ({meta.get('username') or chat_id}) "
            f"msg_id={msg.id}, len={len(message_text)} | {message_text[:50]}{'...' if len(message_text) > 50 else ''}"
        )
        
        # 텍스트가 없고 미디어도 없는 경우 무시
        if not has_text and not has_media:
            mlog.info(f"빈 메시지 무시: chat_id={chat_id}, msg_id={msg.id}")
            return

        # Forward 메시지 확인 및 원본 정보 추출
        is_forward, original_chat_id, original_message_id, original_text = extract_forward_info(msg)
        
        # 기본 텍스트 설정
        if is_forward and original_text:
            text = normalize_text(original_text)
            mlog.info(f"Forward 메시지 감지: 원본 chat_id={original_chat_id}, msg_id={original_message_id}")
        else:
            text = normalize_text(message_text)
        
        # 이미지 처리
        image_content = None
        if has_media and msg.media:
            try:
                # 이미지 다운로드
                image_data = await tg.client.download_media(msg.media, bytes)
                if image_data:
                    # OCR로 텍스트 추출
                    extracted_text = await image_processor.extract_text_from_image(image_data)
                    if extracted_text:
                        image_content = image_processor.analyze_image_content(extracted_text)
                        # 이미지에서 추출한 텍스트를 메인 텍스트에 추가
                        text = f"{text} [이미지 텍스트: {extracted_text}]" if text else f"[이미지 텍스트: {extracted_text}]"
                        mlog.info(f"이미지에서 텍스트 추출: {len(extracted_text)}자")
                    else:
                        image_content = image_processor.analyze_image_content("")
                        mlog.info("이미지에서 텍스트 추출 실패")
            except Exception as e:
                mlog.error(f"이미지 처리 실패: {e}")
        
        # 링크 처리
        link_content = None
        if has_text:
            links = link_processor.extract_links_from_text(message_text)
            if links:
                mlog.info(f"링크 감지: {len(links)}개")
                for link in links[:2]:  # 최대 2개 링크만 처리
                    try:
                        webpage_data = await link_processor.fetch_webpage_content(link)
                        if webpage_data:
                            link_content = link_processor.analyze_link_content(webpage_data)
                            # 링크 내용을 메인 텍스트에 추가
                            link_summary = link_content.get("summary", "")
                            text = f"{text} [링크 내용: {link_summary}]" if text else f"[링크 내용: {link_summary}]"
                            mlog.info(f"링크 내용 분석 완료: {link_content.get('title', '')[:50]}")
                            break  # 첫 번째 링크만 처리
                    except Exception as e:
                        mlog.error(f"링크 처리 실패 ({link}): {e}")
        
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
        # Forward된 메시지인 경우 원본 정보 사용, 아니면 현재 메시지 정보 사용
        message_id = original_message_id if is_forward and original_message_id else msg.id
        author = None
        
        mlog.debug(f"저장할 메시지 정보: chat_id={chat_id}, message_id={message_id}, is_forward={is_forward}")
        
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
            mlog.info(f"Forward 메시지 원본 링크 생성: chat_id={original_chat_id}, msg_id={original_message_id}")
            
            # 원본 채널 메타데이터 가져오기
            original_meta = await get_channel_meta(original_chat_id)
            mlog.info(f"원본 채널 메타데이터: {original_meta}")
            
            # 원본 메시지 링크 생성
            orig_link = build_original_link(
                chat_id=original_chat_id,
                message_id=original_message_id,
                is_public=bool(original_meta.get("is_public")),
                username=original_meta.get("username"),
                internal_id=original_meta.get("internal_id"),
            )
            source_title = original_meta.get("title", f"Unknown Channel {original_chat_id}")
            mlog.info(f"원본 링크 생성 결과: {orig_link}")
        else:
            # 일반 메시지의 경우 현재 채널 링크 사용
            mlog.info(f"일반 메시지 링크 생성: chat_id={chat_id}, msg_id={message_id}")
            
            # 현재 채널 메타데이터 가져오기
            meta = await get_channel_meta(chat_id)
            mlog.info(f"현재 채널 메타데이터: {meta}")
            
            orig_link = build_original_link(
                chat_id=chat_id,
                message_id=message_id,
                is_public=bool(meta.get("is_public")),
                username=meta.get("username"),
                internal_id=meta.get("internal_id"),
            )
            source_title = meta.get("title", "Unknown")
            mlog.info(f"일반 링크 생성 결과: {orig_link}")

        # Importance thresholding
        importance_order = IMPORTANCE_ORDER.get(analysis.importance, 0)
        threshold_order = IMPORTANCE_ORDER.get(settings.important_threshold, 1)
        
        mlog.info(f"중요도 판단: {analysis.importance} (순서: {importance_order}) vs 임계값: {settings.important_threshold} (순서: {threshold_order})")
        
        if importance_order < threshold_order:
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
            mlog.info(f"❌ 전달 제외: 중요도 부족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} < {settings.important_threshold})")
            return

        # Forward to aggregator channel
        mlog.info(f"✅ 전달 승인: 중요도 충족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} >= {settings.important_threshold})")
        
        html = format_html(
            source_title=source_title,
            summary=analysis.summary,
            importance=analysis.importance,
            categories=analysis.categories,
            tags=analysis.tags,
            original_link=orig_link,
            image_content=image_content,
            link_content=link_content,
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


