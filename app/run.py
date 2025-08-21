from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from app.config import load_settings
from app.formatter import build_original_link, format_html
from app.llm import OpenAILLM
from app.storage import SQLiteStore
from app.telegram_client import TG
from app.logging_utils import setup_logging
from app.rules import boost_importance_for_events
from app.image_processor import ImageProcessor
from app.link_processor import LinkProcessor
from app.embedding_client import UpstageEmbeddingClient
from app.sent_message_logger import SentMessageLogger

import logging
import sqlite3
import os
import re
import json


IMPORTANCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def extract_forward_info(msg) -> Tuple[bool, Optional[int], Optional[int], Optional[str]]:
	"""
	메시지가 forward된 것인지 확인하고 원본 정보를 추출
	
	Returns:
		Tuple[is_forward, original_chat_id, original_message_id, original_text]
	"""
	# Telethon 스펙 기반 포워드 감지
	mlog = logging.getLogger("app.msg")
	from telethon import utils as _tg_utils
	fwd = getattr(msg, 'fwd_from', None) or getattr(msg, 'forward', None)
	is_forward = fwd is not None
	mlog.info(f"포워드 감지: is_forward={is_forward}, fwd_type={type(fwd)}")
	
	if is_forward:
		# Forward된 메시지인 경우
		original_chat_id = None
		original_message_id = None
		original_text = getattr(msg, 'message', '')
		
		# Forward 객체 정보 로깅 (디버깅용)
		mlog.info(f"=== FORWARD 정보 추출 시작 ===")
		mlog.info(f"Forward 객체 타입: {type(fwd)}")
		mlog.info(f"Forward 객체 속성: {[attr for attr in dir(fwd) if not attr.startswith('_')]}")
		
		# 원본 채널/채팅 정보 추출
		if hasattr(fwd, 'chat_id'):
			original_chat_id = fwd.chat_id
			mlog.info(f"chat_id에서 추출: {original_chat_id}")
		elif hasattr(fwd, 'channel_id'):
			original_chat_id = fwd.channel_id
			mlog.info(f"channel_id에서 추출: {original_chat_id}")
		elif hasattr(fwd, 'user_id'):
			original_chat_id = fwd.user_id
			mlog.info(f"user_id에서 추출: {original_chat_id}")
		elif hasattr(fwd, 'from_id') and getattr(fwd, 'from_id') is not None:
			# MessageFwdHeader.from_id → PeerChannel/PeerUser/PeerChat
			from_id = fwd.from_id
			mlog.info(f"from_id 타입: {type(from_id)}")
			mlog.info(f"from_id 속성: {[attr for attr in dir(from_id) if not attr.startswith('_')]}")
			try:
				original_chat_id = _tg_utils.get_peer_id(from_id)
				mlog.info(f"utils.get_peer_id(from_id) → {original_chat_id}")
			except Exception as e:
				mlog.info(f"from_id peer 변환 실패: {e}")
		
		# Saved-from 경로 (메시지 링크로 저장된 경우)
		if original_chat_id is None and hasattr(fwd, 'saved_from_peer') and getattr(fwd, 'saved_from_peer') is not None:
			try:
				original_chat_id = _tg_utils.get_peer_id(fwd.saved_from_peer)
				mlog.info(f"saved_from_peer → {original_chat_id}")
			except Exception as e:
				mlog.info(f"saved_from_peer 변환 실패: {e}")
		
		# 원본 메시지 ID 추출
		if hasattr(fwd, 'channel_post') and getattr(fwd, 'channel_post') is not None:
			original_message_id = fwd.channel_post
			mlog.info(f"fwd.channel_post에서 메시지 ID 추출: {original_message_id}")
		elif hasattr(fwd, 'saved_from_msg_id') and getattr(fwd, 'saved_from_msg_id') is not None:
			original_message_id = fwd.saved_from_msg_id
			mlog.info(f"fwd.saved_from_msg_id에서 메시지 ID 추출: {original_message_id}")
		elif hasattr(fwd, 'id') and getattr(fwd, 'id') is not None:
			# 일부 클라이언트가 id 필드를 제공하기도 함
			original_message_id = fwd.id
			mlog.info(f"fwd.id에서 메시지 ID 추출: {original_message_id}")
		
		mlog.info(f"=== FORWARD 정보 추출 결과 ===")
		mlog.info(f"원본 chat_id: {original_chat_id}")
		mlog.info(f"원본 msg_id: {original_message_id}")
		mlog.info(f"원본 텍스트 길이: {len(original_text)}")
		return True, original_chat_id, original_message_id, original_text
	
	# Forward 아님
	mlog.info("포워드 메시지가 아님")
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
    if not settings.upstage_api_key:
        logger.error("Missing UPSTAGE_API_KEY")
        raise RuntimeError("UPSTAGE_API_KEY가 필요합니다. .env를 설정하세요.")
    
    llm = OpenAILLM(settings.openai_api_key, settings.openai_model)
    tg = TG(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash)
    
    # 임베딩, 이미지, 링크 처리기 초기화
    embedding_client = UpstageEmbeddingClient(settings.upstage_api_key)
    image_processor = ImageProcessor()
    link_processor = LinkProcessor()
    sent_logger = SentMessageLogger()
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
            "is_megagroup": getattr(meta, "is_megagroup", False),
            "is_broadcast": getattr(meta, "is_broadcast", not getattr(meta, "is_megagroup", False)),
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
    logger.info(f"=== 소스 채널 메타데이터 로딩 시작 ===")
    for src in settings.source_channels:
        logger.info(f"채널 로딩 중: {src}")
        meta = await ensure_channel_meta(src)
        channel_cache[meta["chat_id"]] = meta
        # 방송 채널 또는 메가그룹 모두 포함하도록 수정
        if not meta.get("is_broadcast", False) and not meta.get("is_megagroup", False):
            logger.info(f"제외(방송 채널/메가그룹 아님): {meta['title']} (@{meta['username'] or 'N/A'}) [ID: {meta['chat_id']}] megagroup={meta.get('is_megagroup')} broadcast={meta.get('is_broadcast')}")
            continue
        chat_filters.append(meta["chat_id"])  # 방송 채널과 메가그룹 모두 포함
        channel_type = "broadcast" if meta.get("is_broadcast") else "megagroup"
        logger.info(f"Listening source: {meta['title']} (@{meta['username'] or 'N/A'}) [ID: {meta['chat_id']}] ({channel_type})")
    
    logger.info(f"=== 모니터링 대상 채널 ID 목록 ===")
    logger.info(f"총 {len(chat_filters)}개 채널: {chat_filters}")

    logger.info(
        "Aggregator=%s, importance>=%s, dedup_window=%sm, similarity>=%s",
        settings.aggregator_channel,
        settings.important_threshold,
        settings.dedup_recent_minutes,
        settings.dedup_similarity_threshold,
    )

    async def handle_message(event):
        mlog = logging.getLogger("app.msg")
        msg = event.message

        # 메시지 처리 시작 로깅
        mlog.info(f"🔍 메시지 처리 시작: chat_id={getattr(event, 'chat_id', 'unknown')}, msg_id={getattr(msg, 'id', 'unknown')}")

        # Use event.chat_id directly; event.chat can be None depending on cache/state
        chat_id = getattr(event, "chat_id", None) or getattr(getattr(event, "chat", None), "id", None)
        if chat_id is None:
            mlog.warning("❌ 메시지 버림: chat_id 없음")
            return

        # 모든 메시지에 대한 기본 로깅 (디버깅용)
        message_text = getattr(msg, "message", "").strip()
        mlog.info(f"📨 메시지 수신: chat_id={chat_id}, msg_id={msg.id}, len={len(message_text)}, preview={message_text[:50]}...")

        # 채널 필터링: chat_id가 -100으로 시작하는 경우만 채널
        if not str(chat_id).startswith("-100"):
            mlog.info(f"❌ 메시지 버림: 채팅방 메시지 (chat_id={chat_id}) - 채널만 모니터링")
            return

        # 댓글/연동 대화방 메시지 무시: reply_to, top_msg, megagroup 등
        try:
            is_comment = bool(getattr(msg, 'reply_to_msg_id', None)) or bool(getattr(msg, 'reply_to', None))
            # 스레드 최상단 메시지가 있는 경우(댓글/토픽)
            has_top_thread = bool(getattr(msg, 'replies', None) and getattr(getattr(msg, 'replies', None), 'forum_topic', False))
        except Exception:
            is_comment = False
            has_top_thread = False
        
        # 댓글/스레드 무시 로직 완화: 실제 댓글만 무시하고 일반 메시지는 허용
        if is_comment and not has_top_thread:
            mlog.info(f"❌ 메시지 버림: 댓글 메시지 (chat_id={chat_id}, msg_id={msg.id})")
            return
        elif has_top_thread:
            mlog.info(f"❌ 메시지 버림: 토픽 스레드 메시지 (chat_id={chat_id}, msg_id={msg.id})")
            return

        # 소스 채널 필터링: 설정된 채널만 처리
        mlog.info(f"채널 필터링 확인: chat_id={chat_id}, chat_filters={chat_filters}")
        if chat_id not in chat_filters:
            # 채널 메타데이터 가져오기
            meta = await get_channel_meta(chat_id)
            message_text = getattr(msg, "message", "").strip()
            
            # 디버깅: 왜 이 채널이 필터에서 제외되었는지 확인
            mlog.info(
                f"미모니터링 채널 메시지: {meta.get('title', 'Unknown')} (@{meta.get('username', 'N/A')}) (chat_id={chat_id}) "
                f"msg_id={msg.id}, len={len(message_text)} | {message_text[:50]}{'...' if len(message_text) > 50 else ''}"
            )
            mlog.info(f"채널 타입: megagroup={meta.get('is_megagroup')}, broadcast={meta.get('is_broadcast')}")
            
            # 방송 채널이 아닌 경우에만 무시 (메가그룹도 허용하도록 수정)
            if not meta.get('is_broadcast', False) and not meta.get('is_megagroup', False):
                mlog.info(f"❌ 메시지 버림: 방송 채널도 메가그룹도 아님 - {meta.get('title', 'Unknown')} (chat_id={chat_id}, msg_id={msg.id})")
                return
            else:
                mlog.info(f"방송 채널 또는 메가그룹 - 처리 진행: {meta.get('title', 'Unknown')}")
                # 필터에 추가
                chat_filters.append(chat_id)
                channel_cache[chat_id] = meta
        else:
            mlog.info(f"모니터링 대상 채널 확인됨: chat_id={chat_id}")

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
        mlog.info(f"현재 처리 중인 채널 chat_id: {chat_id}, 모니터링 대상 여부: {chat_id in chat_filters}")
        
        # 텍스트가 없고 미디어도 없는 경우 무시
        if not has_text and not has_media:
            mlog.info(f"❌ 메시지 버림: 빈 메시지 (chat_id={chat_id}, msg_id={msg.id}) - 텍스트와 미디어 모두 없음")
            return

        # Forward 메시지 확인 및 원본 정보 추출
        is_forward, original_chat_id, original_message_id, original_text = extract_forward_info(msg)
        
        # 포워드 메시지 여부 로깅
        mlog.info(f"메시지 포워드 여부: {is_forward}, 원본 chat_id: {original_chat_id}")
        
        # 포워드 메시지가 아닌데 모니터링 대상이 아닌 채널인 경우 무시
        if not is_forward and chat_id not in chat_filters:
            mlog.info(f"❌ 메시지 버림: 일반 메시지이지만 모니터링 대상이 아닌 채널 (chat_id={chat_id}, msg_id={msg.id})")
            return
        
        # 포워드된 메시지의 경우 원본 채널이 모니터링 대상인지 확인
        if is_forward and original_chat_id:
            # 포워드한 채널 정보 가져오기
            forward_channel_meta = await get_channel_meta(chat_id)
            original_channel_meta = await get_channel_meta(original_chat_id)
            
            mlog.info(f"=== 포워드 메시지 채널 정보 ===")
            mlog.info(f"포워드한 채널: {forward_channel_meta.get('title', 'Unknown')} (@{forward_channel_meta.get('username', 'N/A')}) [ID: {chat_id}]")
            mlog.info(f"원본 채널: {original_channel_meta.get('title', 'Unknown')} (@{original_channel_meta.get('username', 'N/A')}) [ID: {original_chat_id}]")
            mlog.info(f"모니터링 대상 채널 목록: {chat_filters}")
            
            # 포워드 메시지는 원본 채널이 모니터링 대상이 아니어도 처리 (요구사항 4번)
            if original_chat_id not in chat_filters:
                mlog.info(f"포워드 메시지 처리: 원본 채널이 모니터링 대상이 아니지만 포워드 메시지이므로 처리 진행")
            else:
                mlog.info(f"포워드 원본 채널 모니터링 대상: {original_chat_id}")
        elif is_forward and not original_chat_id:
            mlog.warning(f"❌ 메시지 버림: 포워드 메시지이지만 원본 채널 ID를 추출할 수 없음 (chat_id={chat_id}, msg_id={msg.id})")
            return
        
        # 기본 텍스트 설정
        if is_forward and original_text:
            text = original_text.strip()
            raw_for_snippet = original_text
            mlog.info(f"Forward 메시지 감지: 원본 chat_id={original_chat_id}, msg_id={original_message_id}")
        else:
            text = message_text.strip()
            raw_for_snippet = message_text
        
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
                        # 이미지에서 추출한 텍스트를 메인 텍스트에 추가 (텍스트가 있을 때만)
                        if text:
                            text = f"{text} [이미지 텍스트: {extracted_text}]"
                        else:
                            text = f"[이미지 텍스트: {extracted_text}]"
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
        
        # 임베딩 생성 및 중복 제거
        embedding = await embedding_client.get_embedding(text)
        if not embedding:
            mlog.warning(f"임베딩 생성 실패, 메시지 처리 중단: chat_id={chat_id}, msg_id={msg.id}")
            return
        
        embedding_json = json.dumps(embedding)
        now_ts = int(datetime.utcnow().timestamp())
        since_ts = now_ts - settings.dedup_recent_minutes * 60
        
        # Forward된 메시지인 경우 원본 메시지 ID로 중복 체크
        check_message_id = original_message_id if is_forward and original_message_id else msg.id
        check_chat_id = original_chat_id if is_forward and original_chat_id else chat_id
        
        similar = store.find_recent_similar(embedding_json, since_ts, settings.dedup_similarity_threshold, embedding_client)
        if similar:
            similar_chat_id, similar_msg_id, similarity_score = similar
            mlog.info(f"❌ 메시지 버림: 중복 메시지 (현재: chat_id={chat_id}, msg_id={msg.id}, 체크: chat_id={check_chat_id}, msg_id={check_message_id}) - 유사도 점수: {similarity_score:.3f}, 임계값: {settings.dedup_similarity_threshold}")
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
            embedding_value=embedding_json,
        )

        # LLM analysis
        try:
            analysis = llm.analyze(text)
        except Exception as e:
            logging.getLogger("app.llm").exception("LLM analyze failed")
            mlog.error(f"❌ 메시지 버림: LLM 분석 실패 (chat_id={chat_id}, msg_id={msg.id}) - {e}")
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
        threshold_order = IMPORTANCE_ORDER.get(settings.important_threshold, 0)  # low일 때 0으로 수정
        
        mlog.info(f"중요도 판단: {analysis.importance} (순서: {importance_order}) vs 임계값: {settings.important_threshold} (순서: {threshold_order})")
        
        # 중요도 임계값 로직 수정: low 설정 시 모든 메시지 전송
        should_forward = importance_order >= threshold_order
        
        # 무의미한 메시지 필터링 강화
        meaningless_patterns = [
            r'^\s*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?~`]+\s*$',  # 특수문자만
            r'^\s*[a-zA-Z0-9]{1,3}\s*$',  # 1-3자리 영숫자만
            r'^\s*(안녕|하이|ㅎㅇ|ㅎㅇㅎㅇ|ㅋㅋ|ㅎㅎ|ㅇㅇ|ㄴㄴ|ㅇㅈ|ㄴㄴㄴ)\s*$',  # 인사말만
            r'^\s*(좋아요|👍|❤️|💕|💖|💗|💘|💙|💚|💛|💜|🖤|🤍|🤎)\s*$',  # 이모지만
            r'^\s*(ㅇ|ㄴ|ㅇㅇ|ㄴㄴ|ㅇㅈ|ㄴㄴㄴ)\s*$',  # 짧은 답변만
        ]
        
        is_meaningless = any(re.search(pattern, text, re.IGNORECASE) for pattern in meaningless_patterns)
        
        # 추가 조건: 텍스트 길이가 일정 이상이거나 특별한 키워드가 포함된 경우
        if not should_forward and len(text.strip()) > 30 and not is_meaningless:  # 50자에서 30자로 완화
            # 텍스트가 충분히 긴 경우 low 중요도라도 전송 고려
            should_forward = True
            mlog.info(f"텍스트 길이로 인한 전송 승인: {len(text)}자")
        
        # 추가 조건: 특별한 키워드가 포함된 경우
        important_keywords = ['airdrop', 'launch', 'listing', 'whitelist', 'presale', 'ico', 'ido', 'nft', 'dao', 'defi', 'gamefi', 'metaverse']
        if not should_forward and any(keyword in text.lower() for keyword in important_keywords):
            should_forward = True
            mlog.info(f"중요 키워드로 인한 전송 승인: {[k for k in important_keywords if k in text.lower()]}")
        
        # 추가 조건: 이미지나 링크가 포함된 경우
        if not should_forward and (has_media or link_content):
            should_forward = True
            mlog.info(f"미디어/링크 포함으로 인한 전송 승인: has_media={has_media}, has_link={bool(link_content)}")
        
        # 무의미한 메시지는 무조건 차단
        if is_meaningless:
            should_forward = False
            mlog.info(f"❌ 무의미한 메시지 차단: {text[:50]}...")
        
        if not should_forward:
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
            mlog.info(f"❌ 메시지 버림: 중요도 부족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} < {settings.important_threshold}, 텍스트 길이: {len(text)}자)")
            return

        # Forward to aggregator channel
        mlog.info(f"✅ 전달 승인: 중요도 충족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} >= {settings.important_threshold})")
        
        # 포워드 정보 준비
        forward_info = None
        if is_forward and original_chat_id:
            forward_channel_meta = await get_channel_meta(chat_id)
            original_channel_meta = await get_channel_meta(original_chat_id)
            forward_info = {
                "forward_channel": f"{forward_channel_meta.get('title', 'Unknown')} (@{forward_channel_meta.get('username', 'N/A')})",
                "original_channel": f"{original_channel_meta.get('title', 'Unknown')} (@{original_channel_meta.get('username', 'N/A')})"
            }
        
        html = format_html(
            source_title=source_title,
            summary=analysis.summary,
            importance=analysis.importance,
            categories=analysis.categories,
            tags=analysis.tags,
            money_making_info=analysis.money_making_info,
            action_guide=analysis.action_guide,
            original_link=orig_link,
            image_content=image_content,
            link_content=link_content,
            forward_info=forward_info,
            original_snippet=(raw_for_snippet[:400] + ("…" if len(raw_for_snippet) > 400 else "")) if raw_for_snippet else None,
        )
        try:
            await tg.send_html(settings.aggregator_channel, html)
            mlog.info(f"✅ 전송 성공: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) → {settings.aggregator_channel}")
            
            # 전송된 메시지 로깅
            sent_logger.log_sent_message(
                source_channel=meta.get('title', 'Unknown'),
                source_username=meta.get('username', 'unknown'),
                message_id=message_id,
                importance=analysis.importance,
                categories=analysis.categories,
                tags=analysis.tags,
                summary=analysis.summary,
                money_making_info=analysis.money_making_info,
                action_guide=analysis.action_guide,
                original_link=orig_link,
                has_image=has_media,
                has_link=bool(link_content),
                is_forward=is_forward,
                forward_info=forward_info,
            )
        except Exception as e:
            logging.getLogger("app.tg").exception("Failed to send message to aggregator")
            mlog.error(f"❌ 전송 실패: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) → {settings.aggregator_channel} - {e}")
            return

        # Update DB
        store.update_analysis(
            chat_id=chat_id,
            message_id=message_id,
            importance=analysis.importance,
            categories=",".join(analysis.categories),
            tags=",".join(analysis.tags),
            summary=analysis.summary,
            money_making_info=analysis.money_making_info,
            action_guide=analysis.action_guide,
            original_link=orig_link,
        )
        forward_log = f" [FORWARD from {original_chat_id}:{original_message_id}]" if is_forward else ""
        mlog.info(f"✅ 메시지 처리 완료: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance}){forward_log}")

    # 모든 메시지를 받고 내부에서 필터링 (Telethon 이벤트 핸들러 제한 우회)
    # 이벤트 핸들러를 더 명시적으로 등록
    from telethon import events
    
    @tg.client.on(events.NewMessage)
    async def new_message_handler(event):
        logger.info(f"🔔 이벤트 핸들러 호출됨: chat_id={getattr(event, 'chat_id', 'unknown')}, msg_id={getattr(event.message, 'id', 'unknown')}")
        await handle_message(event)
    
    # 추가 디버깅: 이벤트 핸들러가 등록되었는지 확인
    logger.info(f"등록된 이벤트 핸들러 수: {len(tg.client.list_event_handlers())}")
    
    # 채널 접근 권한 테스트
    async def test_channel_access():
        logger.info("=== 채널 접근 권한 테스트 시작 ===")
        for channel_id in chat_filters:
            try:
                # 채널 정보 가져오기 시도
                chat = await tg.client.get_entity(channel_id)
                logger.info(f"✅ 채널 접근 가능: {chat.title} (ID: {channel_id})")
                
                # 최근 메시지 가져오기 시도 (권한 확인)
                try:
                    messages = await tg.client.get_messages(chat, limit=1)
                    if messages:
                        logger.info(f"✅ 메시지 읽기 권한 있음: {chat.title} (최근 메시지 ID: {messages[0].id})")
                    else:
                        logger.info(f"⚠️ 메시지 없음: {chat.title}")
                except Exception as e:
                    logger.warning(f"❌ 메시지 읽기 권한 없음: {chat.title} - {e}")
                    
            except Exception as e:
                logger.error(f"❌ 채널 접근 불가: ID {channel_id} - {e}")
        
        logger.info("=== 채널 접근 권한 테스트 완료 ===")
    
    # 채널 접근 테스트 실행
    await test_channel_access()
    
    # 폴링 방식으로 메시지 수신 (실시간 수신 대안)
    async def poll_messages():
        logger.info("=== 폴링 방식 메시지 수신 시작 ===")
        last_message_ids = {}  # 채널별 마지막 메시지 ID 추적
        
        while True:
            try:
                for channel_id in chat_filters:
                    try:
                        # 채널 정보 가져오기
                        chat = await tg.client.get_entity(channel_id)
                        
                        # 최근 메시지 가져오기 (최대 10개)
                        messages = await tg.client.get_messages(chat, limit=10)
                        
                        if not messages:
                            continue
                            
                        # 마지막 메시지 ID 확인
                        latest_msg_id = messages[0].id
                        last_known_id = last_message_ids.get(channel_id, latest_msg_id - 1)
                        
                        # 새로운 메시지가 있는지 확인
                        if latest_msg_id > last_known_id:
                            logger.info(f"🔍 폴링으로 새 메시지 발견: {chat.title} (ID: {latest_msg_id})")
                            
                            # 새로운 메시지들 처리
                            for msg in reversed(messages):
                                if msg.id > last_known_id:
                                    # 메시지를 이벤트 객체로 래핑하여 handle_message 호출
                                    try:
                                        # 메시지 객체를 이벤트 객체로 래핑
                                        class EventWrapper:
                                            def __init__(self, message, chat_id):
                                                self.message = message
                                                self.chat_id = chat_id
                                                self.chat = None
                                        
                                        event = EventWrapper(msg, channel_id)
                                        await handle_message(event)
                                        logger.info(f"✅ 폴링 메시지 처리 완료: {chat.title} (ID: {msg.id})")
                                    except Exception as e:
                                        logger.error(f"❌ 폴링 메시지 처리 실패: {chat.title} (ID: {msg.id}) - {e}")
                            
                            # 마지막 메시지 ID 업데이트
                            last_message_ids[channel_id] = latest_msg_id
                            
                    except Exception as e:
                        logger.warning(f"폴링 중 오류 (채널 {channel_id}): {e}")
                
                # 30초 대기
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"폴링 루프 오류: {e}")
                await asyncio.sleep(60)  # 오류 시 1분 대기
    
    # 폴링 태스크 시작
    asyncio.create_task(poll_messages())
    
    logger.info("Listening... (Ctrl+C to stop)")
    
    # 연결 상태 확인
    logger.info(f"Telethon 연결 상태: {tg.client.is_connected()}")
    logger.info(f"이벤트 핸들러 등록 완료 - 모든 메시지 수신 대기 중")
    
    # 메시지 처리 통계 주기적 출력
    async def print_stats():
        while True:
            await asyncio.sleep(300)  # 5분마다
            try:
                total_messages = store.get_message_count()
                logger.info(f"=== 처리 통계 === 총 메시지: {total_messages}, 모니터링 채널: {len(chat_filters)}개")
                
                # 중요도별 통계
                importance_stats = store.get_importance_stats()
                if importance_stats:
                    logger.info(f"중요도별 통계: {importance_stats}")
                
                # 최근 처리된 메시지 수
                recent_count = store.get_recent_message_count(300)  # 5분 내
                logger.info(f"최근 5분 처리: {recent_count}개 메시지")
                
                # 연결 상태 확인
                logger.info(f"Telethon 연결 상태: {tg.client.is_connected()}")
                
                # 이벤트 핸들러 상태 확인
                logger.info(f"등록된 이벤트 핸들러 수: {len(tg.client.list_event_handlers())}")
                
            except Exception as e:
                logger.error(f"통계 출력 실패: {e}")
    
    # 통계 출력 태스크 시작
    asyncio.create_task(print_stats())
    
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())


