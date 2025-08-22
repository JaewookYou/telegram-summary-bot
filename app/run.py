from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from app.config import load_settings, load_source_channels, add_source_channel, remove_source_channel
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
from app.bot_notifier import BotNotifier

import logging
import sqlite3
import os
import re
import json
from telethon import utils


IMPORTANCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def format_time(timestamp):
    """시간 정보를 표준화된 형태로 포맷팅"""
    if timestamp:
        dt = datetime.fromtimestamp(timestamp.timestamp())
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return None


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
				# from_id가 유효한 peer 객체인지 확인하고 타입 체크 (Channel, User, Chat 등 허용)
				if (hasattr(from_id, 'channel_id') or hasattr(from_id, 'user_id') or hasattr(from_id, 'chat_id')) and not isinstance(from_id, str) and hasattr(from_id, '__class__'):
					original_chat_id = _tg_utils.get_peer_id(from_id)
					mlog.info(f"utils.get_peer_id(from_id) → {original_chat_id}")
				else:
					mlog.info(f"유효하지 않은 from_id 타입: {type(from_id)}, 클래스: {getattr(from_id, '__class__', 'Unknown')}")
			except Exception as e:
				mlog.info(f"from_id peer 변환 실패: {e}")
		
		# Saved-from 경로 (메시지 링크로 저장된 경우)
		if original_chat_id is None and hasattr(fwd, 'saved_from_peer') and getattr(fwd, 'saved_from_peer') is not None:
			try:
				# saved_from_peer도 타입 체크 (Channel, User, Chat 등 허용)
				if (not isinstance(fwd.saved_from_peer, str) and 
					hasattr(fwd.saved_from_peer, '__class__')):
					original_chat_id = _tg_utils.get_peer_id(fwd.saved_from_peer)
					mlog.info(f"saved_from_peer → {original_chat_id}")
				else:
					mlog.info(f"유효하지 않은 saved_from_peer 타입: {type(fwd.saved_from_peer)}, 클래스: {getattr(fwd.saved_from_peer, '__class__', 'Unknown')}")
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
    tg = TG(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash, settings.bot_token)
    
    # 임베딩, 이미지, 링크 처리기 초기화
    embedding_client = UpstageEmbeddingClient(settings.upstage_api_key)
    image_processor = ImageProcessor()
    link_processor = LinkProcessor()
    sent_logger = SentMessageLogger()
    
    # Upstage.ai API 연결 테스트
    logger.info("Upstage.ai API 연결 테스트 중...")
    api_test_result = await embedding_client.test_connection()
    if not api_test_result:
        logger.error("Upstage.ai API 연결 실패. 임베딩 기반 중복 제거가 작동하지 않습니다.")
        logger.error("API 키를 확인하거나 네트워크 연결을 점검하세요.")
    else:
        logger.info("Upstage.ai API 연결 성공")
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

    channel_cache: Dict[int, dict] = {}  # 메타데이터 캐시
    entity_cache: Dict[int, object] = {}  # Telethon 엔티티 캐시
    
    def clear_old_cache():
        """오래된 캐시 정리 (메모리 관리)"""
        if len(entity_cache) > 100:  # 100개 이상이면 오래된 것부터 정리
            logger.info(f"캐시 정리: {len(entity_cache)}개 엔티티")
            # 가장 오래된 20개 제거
            keys_to_remove = list(entity_cache.keys())[:20]
            for key in keys_to_remove:
                del entity_cache[key]
            logger.info(f"캐시 정리 완료: {len(entity_cache)}개 엔티티 남음")

    async def ensure_channel_meta(identifier: str) -> dict:
        try:
            meta = await tg.iter_channel_meta(identifier)
            return {
                "chat_id": meta.chat_id,
                "title": meta.title,
                "username": meta.username,
                "internal_id": meta.internal_id,
                "is_public": meta.is_public,
                "chat_type": getattr(meta, "chat_type", "unknown"),
                "is_forum": getattr(meta, "is_forum", False),
                "linked_chat_id": getattr(meta, "linked_chat_id", None),
                "has_chat": getattr(meta, "has_chat", False),
                "is_megagroup": getattr(meta, "is_megagroup", False),
                "is_broadcast": getattr(meta, "is_broadcast", not getattr(meta, "is_megagroup", False)),
            }
        except ValueError as e:
            # 채널을 찾을 수 없는 경우 (삭제되었거나 접근 권한 없음)
            logger.error(f"채널을 찾을 수 없음: {identifier}, 에러: {e}")
            # 해당 채널을 SOURCE_CHANNELS에서 제거
            if remove_source_channel(identifier):
                logger.info(f"채널 {identifier}을 SOURCE_CHANNELS에서 제거했습니다.")
            else:
                logger.warning(f"채널 {identifier} 제거 실패")
            
            # 기본 메타데이터 반환 (에러 방지용)
            return {
                "chat_id": identifier,
                "title": f"Deleted/Inaccessible Channel {identifier}",
                "username": None,
                "internal_id": None,
                "is_public": False,
                "chat_type": "unknown",
                "is_forum": False,
                "linked_chat_id": None,
                "has_chat": False,
                "is_megagroup": False,
                "is_broadcast": False,
            }
        except Exception as e:
            # 기타 예외 처리
            logger.error(f"채널 메타데이터 가져오기 실패: {identifier}, 에러: {e}")
            return {
                "chat_id": identifier,
                "title": f"Error Channel {identifier}",
                "username": None,
                "internal_id": None,
                "is_public": False,
                "chat_type": "unknown",
                "is_forum": False,
                "linked_chat_id": None,
                "has_chat": False,
                "is_megagroup": False,
                "is_broadcast": False,
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
                # entity가 유효한 Peer 객체인지 확인 (Channel, User, Chat 등 허용)
                if (hasattr(entity, 'id') and 
                    not isinstance(entity, str) and 
                    hasattr(entity, '__class__')):
                    peer_id = utils.get_peer_id(entity)
                    if isinstance(peer_id, int):
                        peer_abs = abs(peer_id)
                        s = str(peer_abs)
                        if s.startswith("100"):
                            meta["internal_id"] = int(s[3:])
                else:
                    logger.warning(f"유효하지 않은 엔티티 타입으로 internal_id 계산 건너뜀: {type(entity)}")
            
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

    # Preload source channel metas and entities
    chat_filters = []
    removed_channels = set()  # 제거된 채널 목록을 메모리에 유지
    logger.info(f"=== 소스 채널 메타데이터 및 엔티티 로딩 시작 ===")
    
    # 동적으로 SOURCE_CHANNELS 로드
    source_channels = load_source_channels()
    logger.info(f"로드된 SOURCE_CHANNELS: {source_channels}")
    
    channels_to_remove = []  # 제거할 채널 목록
    
    for src in source_channels:
        logger.info(f"채널 로딩 중: {src}")
        try:
            meta = await ensure_channel_meta(src)
            channel_cache[meta["chat_id"]] = meta
            
            # 삭제되었거나 접근할 수 없는 채널인지 확인
            if "Deleted/Inaccessible" in meta.get("title", "") or "Error" in meta.get("title", ""):
                logger.warning(f"🚫 삭제되었거나 접근할 수 없는 채널 건너뜀: {src}")
                continue
            
            # 엔티티도 미리 로딩하여 캐시에 저장
            try:
                entity = await tg.client.get_entity(src)
                entity_cache[meta["chat_id"]] = entity
                logger.info(f"엔티티 캐시 저장: {meta['title']} (ID: {meta['chat_id']})")
            except Exception as e:
                logger.warning(f"엔티티 로딩 실패: {src}, 에러: {e}")
        except Exception as e:
            logger.error(f"채널 로딩 중 예외 발생: {src}, 에러: {e}")
            continue
        
        # 채팅 기능 유무에 따른 필터링 (채팅 기능이 있으면 제거, 없으면 추가)
        has_chat = meta.get("has_chat", False)
        chat_type = meta.get("chat_type", "unknown")
        
        if has_chat:
            # 채팅 기능이 있는 경우 제거 (사람들이 대화할 수 있음)
            chat_type_info = f" ({chat_type})"
            if chat_type == "supergroup" and meta.get("is_forum", False):
                chat_type_info += " (토픽 기능 활성)"
            
            # Bot API 권한 정보 로깅
            permission_info = ""
            if meta.get("username"):
                bot_permissions = await tg.get_chat_permissions(f"@{meta['username']}")
                if bot_permissions:
                    can_send = bot_permissions.get("can_send_messages", False)
                    join_to_send = bot_permissions.get("join_to_send_messages", False)
                    permission_info = f" [Bot API: can_send={can_send}, join_to_send={join_to_send}]"
            
            logger.warning(f"🚫 채팅 기능 있음 제거: {meta['title']} (@{meta['username'] or 'N/A'}) [ID: {meta['chat_id']}]{chat_type_info}{permission_info} - 사람들이 대화할 수 있으므로 SOURCE_CHANNELS에서 제거")
            channels_to_remove.append(src)
            removed_channels.add(src)  # 제거된 채널 목록에 추가
            continue
        else:
            # 채팅 기능이 없는 경우 추가 (순수 방송 채널)
            chat_filters.append(meta["chat_id"])
            
            # 연결된 채널/그룹 정보 로깅
            linked_info = ""
            if meta.get("linked_chat_id"):
                linked_info = f" (연결된 채널/그룹: {meta['linked_chat_id']})"
            
            # Bot API 권한 정보 로깅
            permission_info = ""
            if meta.get("username"):
                bot_permissions = await tg.get_chat_permissions(f"@{meta['username']}")
                if bot_permissions:
                    can_send = bot_permissions.get("can_send_messages", False)
                    join_to_send = bot_permissions.get("join_to_send_messages", False)
                    permission_info = f" [Bot API: can_send={can_send}, join_to_send={join_to_send}]"
            
            logger.info(f"✅ 순수 방송 채널 추가: {meta['title']} (@{meta['username'] or 'N/A'}) [ID: {meta['chat_id']}] ({chat_type}){linked_info}{permission_info}")
    
    # 그룹들을 SOURCE_CHANNELS에서 제거
    for channel_to_remove in channels_to_remove:
        if remove_source_channel(channel_to_remove):
            logger.info(f"✅ .env에서 제거 완료: {channel_to_remove}")
        else:
            logger.error(f"❌ .env에서 제거 실패: {channel_to_remove}")
    
    logger.info(f"=== 모니터링 대상 채널 ID 목록 ===")
    logger.info(f"총 {len(chat_filters)}개 채널: {chat_filters}")

    # 봇 알림 기능 초기화
    bot_notifier = BotNotifier(settings)
    if bot_notifier.personal_chat_id:
        logger.info(f"✅ 봇 개인 알림 활성화: {bot_notifier.personal_chat_id}")
    else:
        logger.warning("⚠️ 봇 개인 알림 비활성화: PERSONAL_CHAT_ID 설정 필요")
    
    if bot_notifier.important_bot_token:
        logger.info(f"✅ 중요 봇 알림 활성화: {bot_notifier.important_bot_token[:20]}...")
    else:
        logger.warning("⚠️ 중요 봇 알림 비활성화: IMPORTANT_BOT_TOKEN 설정 필요")

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

        # numeric_chat_id가 정의되지 않은 경우 안전하게 처리
        if 'numeric_chat_id' not in locals():
            mlog.warning(f"numeric_chat_id가 정의되지 않음, chat_id 사용: {chat_id}")
            numeric_chat_id = chat_id
        
        # 중복 메시지 체크를 먼저 수행 (리소스 절약)
        if store.is_message_processed(numeric_chat_id, msg.id):
            mlog.info(f"⏭️ 이미 처리된 메시지 건너뜀: chat_id={numeric_chat_id}, msg_id={msg.id}")
            return

        # 모든 메시지에 대한 기본 로깅 (디버깅용)
        message_text = getattr(msg, "message", "").strip()
        mlog.info(f"📨 메시지 수신: chat_id={chat_id}, msg_id={msg.id}, len={len(message_text)}, preview={message_text[:50]}...")

        # 채널 필터링: chat_id가 -100으로 시작하거나 @username 형태인 경우 채널
        chat_id_str = str(chat_id)
        is_channel = chat_id_str.startswith("-100") or chat_id_str.startswith("@")
        
        if not is_channel:
            mlog.info(f"❌ 메시지 버림: 채팅방 메시지 (chat_id={chat_id}) - 채널만 모니터링")
            return

        # 채널 댓글 스레드 감지 및 처리
        try:
            # 메시지 스레드 ID 확인 (채널 댓글 스레드)
            message_thread_id = getattr(msg, 'message_thread_id', None)
            is_comment = bool(getattr(msg, 'reply_to_msg_id', None)) or bool(getattr(msg, 'reply_to', None))
            
            # 스레드 최상단 메시지가 있는 경우(댓글/토픽)
            has_top_thread = bool(getattr(msg, 'replies', None) and getattr(getattr(msg, 'replies', None), 'forum_topic', False))
            
            # 채널 댓글 스레드 감지: supergroup이고 message_thread_id가 존재하는 경우
            if message_thread_id is not None:
                # 채널 메타데이터에서 타입 확인
                meta = await get_channel_meta(chat_id)
                if meta.get("chat_type") == "supergroup":
                    mlog.info(f"❌ 메시지 버림: 채널 댓글 스레드 메시지 (chat_id={chat_id}, msg_id={msg.id}, thread_id={message_thread_id})")
                    return
            
            # 일반 댓글/스레드 무시 로직
            if is_comment and not has_top_thread:
                mlog.info(f"❌ 메시지 버림: 댓글 메시지 (chat_id={chat_id}, msg_id={msg.id})")
                return
            elif has_top_thread:
                mlog.info(f"❌ 메시지 버림: 토픽 스레드 메시지 (chat_id={chat_id}, msg_id={msg.id})")
                return
                
        except Exception as e:
            mlog.warning(f"채널 댓글 스레드 감지 중 오류: {e}")
            # 오류 발생 시 기본적으로 처리 진행

        # @username 형태의 chat_id를 숫자 ID로 변환
        numeric_chat_id = chat_id
        if isinstance(chat_id, str) and chat_id.startswith("@"):
            try:
                # @username을 숫자 ID로 변환
                entity = await tg.client.get_entity(chat_id)
                # entity가 유효한지 확인하고 타입 체크 (Channel, User, Chat 등 허용)
                if (hasattr(entity, 'id') and 
                    not isinstance(entity, str) and 
                    hasattr(entity, '__class__')):
                    numeric_chat_id = utils.get_peer_id(entity)
                    mlog.info(f"@username을 숫자 ID로 변환: {chat_id} → {numeric_chat_id}")
                else:
                    mlog.warning(f"유효하지 않은 엔티티 타입: {chat_id}, 타입: {type(entity)}, 클래스: {getattr(entity, '__class__', 'Unknown')}")
                    return
            except Exception as e:
                mlog.warning(f"@username을 숫자 ID로 변환 실패: {chat_id}, 에러: {e}")
                return
        
        # numeric_chat_id가 정의되지 않은 경우 안전하게 처리
        if 'numeric_chat_id' not in locals():
            mlog.warning(f"numeric_chat_id가 정의되지 않음, chat_id 사용: {chat_id}")
            numeric_chat_id = chat_id

        # 소스 채널 필터링: 설정된 채널만 처리
        mlog.info(f"채널 필터링 확인: chat_id={numeric_chat_id}, chat_filters={chat_filters}")
        
        # 제거된 채널인지 확인
        if numeric_chat_id in removed_channels:
            mlog.info(f"❌ 메시지 버림: 제거된 채널 - {numeric_chat_id}")
            return
        
        if numeric_chat_id not in chat_filters:
            # 채널 메타데이터 가져오기
            meta = await get_channel_meta(numeric_chat_id)
            message_text = getattr(msg, "message", "").strip()
            
            # 디버깅: 왜 이 채널이 필터에서 제외되었는지 확인
            mlog.info(
                f"미모니터링 채널 메시지: {meta.get('title', 'Unknown')} (@{meta.get('username', 'N/A')}) (chat_id={numeric_chat_id}) "
                f"msg_id={msg.id}, len={len(message_text)} | {message_text[:50]}{'...' if len(message_text) > 50 else ''}"
            )
            mlog.info(f"채널 타입: megagroup={meta.get('is_megagroup')}, broadcast={meta.get('is_broadcast')}")
            
            # 방송 채널이 아닌 경우에만 무시 (메가그룹도 허용하도록 수정)
            if not meta.get('is_broadcast', False) and not meta.get('is_megagroup', False):
                mlog.info(f"❌ 메시지 버림: 방송 채널도 메가그룹도 아님 - {meta.get('title', 'Unknown')} (chat_id={numeric_chat_id}, msg_id={msg.id})")
                return
            else:
                mlog.info(f"방송 채널 또는 메가그룹 - 처리 진행: {meta.get('title', 'Unknown')}")
                # 필터에 추가
                chat_filters.append(numeric_chat_id)
                channel_cache[numeric_chat_id] = meta
        else:
            mlog.info(f"모니터링 대상 채널 확인됨: chat_id={numeric_chat_id}")

        # 메시지 내용 분석
        message_text = getattr(msg, "message", "").strip()
        has_text = bool(message_text)
        has_media = bool(msg.media)
        
        # 모든 수신 메시지 로깅 (INFO 레벨)
        meta = channel_cache.get(numeric_chat_id) or {}
        mlog.info(
            f"수신 메시지: {meta.get('title','Unknown')} ({meta.get('username') or numeric_chat_id}) "
            f"msg_id={msg.id}, len={len(message_text)} | {message_text[:50]}{'...' if len(message_text) > 50 else ''}"
        )
        mlog.info(f"현재 처리 중인 채널 chat_id: {numeric_chat_id}, 모니터링 대상 여부: {numeric_chat_id in chat_filters}")
        
        # 텍스트가 없고 미디어도 없는 경우 무시
        if not has_text and not has_media:
            mlog.info(f"❌ 메시지 버림: 빈 메시지 (chat_id={numeric_chat_id}, msg_id={msg.id}) - 텍스트와 미디어 모두 없음")
            return

        # Forward 메시지 확인 및 원본 정보 추출
        is_forward, original_chat_id, original_message_id, original_text = extract_forward_info(msg)
        
        # 포워드 메시지 여부 로깅
        mlog.info(f"메시지 포워드 여부: {is_forward}, 원본 chat_id: {original_chat_id}")
        
        # 포워드 메시지가 아닌데 모니터링 대상이 아닌 채널인 경우 무시
        if not is_forward and numeric_chat_id not in chat_filters:
            mlog.info(f"❌ 메시지 버림: 일반 메시지이지만 모니터링 대상이 아닌 채널 (chat_id={numeric_chat_id}, msg_id={msg.id})")
            return
        
        # 포워드된 메시지의 경우 원본 채널이 모니터링 대상인지 확인
        if is_forward and original_chat_id:
            # 포워드한 채널 정보 가져오기
            forward_channel_meta = await get_channel_meta(numeric_chat_id)
            original_channel_meta = await get_channel_meta(original_chat_id)
            
            mlog.info(f"=== 포워드 메시지 채널 정보 ===")
            mlog.info(f"포워드한 채널: {forward_channel_meta.get('title', 'Unknown')} (@{forward_channel_meta.get('username', 'N/A')}) [ID: {numeric_chat_id}]")
            mlog.info(f"원본 채널: {original_channel_meta.get('title', 'Unknown')} (@{original_channel_meta.get('username', 'N/A')}) [ID: {original_chat_id}]")
            mlog.info(f"모니터링 대상 채널 목록: {chat_filters}")
            
            # 원본 채널이 모니터링 대상이 아닌 경우 자동으로 추가
            if original_chat_id not in chat_filters:
                mlog.info(f"🔍 새로운 원본 채널 발견: {original_channel_meta.get('title', 'Unknown')} (@{original_channel_meta.get('username', 'N/A')}) [ID: {original_chat_id}]")
                
                # 원본 채널을 SOURCE_CHANNELS에 추가 (@username 형태로)
                original_channel_str = str(original_chat_id)
                
                # @username 형태로 변환 시도
                try:
                    from app.config import get_channel_username_async
                    username_form = await get_channel_username_async(original_channel_str, tg.client)
                    mlog.info(f"채널 ID 변환: {original_channel_str} → {username_form}")
                except Exception as e:
                    mlog.warning(f"채널 ID 변환 실패, 원본 사용: {e}")
                    username_form = original_channel_str
                
                if add_source_channel(username_form):
                    mlog.info(f"✅ 원본 채널을 SOURCE_CHANNELS에 추가 완료: {username_form}")
                    # chat_filters에 즉시 추가
                    chat_filters.append(original_chat_id)
                    # 채널 캐시에 추가
                    channel_cache[original_chat_id] = original_channel_meta
                else:
                    mlog.warning(f"⚠️ 원본 채널 추가 실패 또는 이미 존재: {username_form}")
                
                mlog.info(f"포워드 메시지 처리: 원본 채널이 모니터링 대상이 아니었지만 자동 추가 후 처리 진행")
            else:
                mlog.info(f"포워드 원본 채널 모니터링 대상: {original_chat_id}")
        elif is_forward and not original_chat_id:
            mlog.warning(f"❌ 메시지 버림: 포워드 메시지이지만 원본 채널 ID를 추출할 수 없음 (chat_id={numeric_chat_id}, msg_id={msg.id})")
            return
        
        # 기본 텍스트 설정 (None 처리 추가)
        if is_forward and original_text:
            text = original_text.strip() if original_text else ""
            raw_for_snippet = original_text or ""
            mlog.info(f"Forward 메시지 감지: 원본 chat_id={original_chat_id}, msg_id={original_message_id}")
        else:
            text = message_text.strip() if message_text else ""
            raw_for_snippet = message_text or ""
        
        # 텍스트가 비어있는 경우 처리
        if not text:
            mlog.warning(f"❌ 메시지 버림: 텍스트가 비어있음 (chat_id={numeric_chat_id}, msg_id={msg.id})")
            return
        
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
        extracted_links = []
        if has_text:
            links = link_processor.extract_links_from_text(message_text)
            if links:
                mlog.info(f"링크 감지: {len(links)}개 - {links}")
                extracted_links = links  # 모든 링크 저장
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
        
        # 임베딩 생성 및 중복 제거 (원문 기준)
        # 포워딩된 메시지의 경우 원본 텍스트로 임베딩 생성
        embedding_text = text  # 이미 포워딩된 메시지의 경우 원본 텍스트가 text에 설정됨
        
        # 텍스트 해시 생성 (정확한 중복 제거용)
        import hashlib
        text_hash = hashlib.md5(embedding_text.encode('utf-8')).hexdigest()
        
        embedding = await embedding_client.get_embedding(embedding_text)
        if not embedding:
            mlog.warning(f"임베딩 생성 실패, 중복 제거 없이 처리 계속: chat_id={chat_id}, msg_id={msg.id}")
            # 임베딩 실패 시에도 메시지 처리를 계속하되, 중복 제거는 건너뜀
            embedding_json = "[]"  # 빈 임베딩으로 설정
        else:
            embedding_json = json.dumps(embedding)
        now_ts = int(datetime.utcnow().timestamp())
        since_ts = now_ts - settings.dedup_recent_minutes * 60
        
        # Forward된 메시지인 경우 원본 메시지 ID로 중복 체크
        check_message_id = original_message_id if is_forward and original_message_id else msg.id
        check_chat_id = original_chat_id if is_forward and original_chat_id else chat_id
        
        # 1단계: 정확한 텍스트 해시 중복 제거
        exact_duplicate = store.find_exact_duplicate(text_hash, since_ts)
        if exact_duplicate:
            duplicate_chat_id, duplicate_msg_id = exact_duplicate
            mlog.info(f"❌ 메시지 버림: 정확한 중복 메시지 (현재: chat_id={chat_id}, msg_id={msg.id}, 중복: chat_id={duplicate_chat_id}, msg_id={duplicate_msg_id})")
            mlog.info(f"중복 제거 기준 텍스트: {embedding_text[:100]}...")
            return  # exact duplicate
        
        # 2단계: 임베딩 기반 유사도 중복 제거
        if embedding_json != "[]":
            similar = store.find_recent_similar(embedding_json, since_ts, settings.dedup_similarity_threshold, embedding_client)
            if similar:
                similar_chat_id, similar_msg_id, similarity_score = similar
                mlog.info(f"❌ 메시지 버림: 유사한 중복 메시지 (현재: chat_id={chat_id}, msg_id={msg.id}, 체크: chat_id={check_chat_id}, msg_id={check_message_id}) - 유사도 점수: {similarity_score:.3f}, 임계값: {settings.dedup_similarity_threshold}")
                mlog.info(f"중복 제거 기준 텍스트: {embedding_text[:100]}...")
                return  # similar duplicate
        else:
            mlog.info(f"임베딩 없음, 유사도 중복 제거 건너뜀: chat_id={chat_id}, msg_id={msg.id}")

        # Insert preliminary record
        # Forward된 메시지인 경우 원본 정보 사용, 아니면 현재 메시지 정보 사용
        message_id = original_message_id if is_forward and original_message_id else msg.id
        author = None
        
        # numeric_chat_id 사용 (이미 숫자 ID로 변환됨)
        chat_id_to_use = numeric_chat_id
        
        # chat_id가 정수인지 확인하고 변환
        if not isinstance(chat_id_to_use, int):
            try:
                chat_id_to_use = int(chat_id_to_use)
                mlog.info(f"chat_id를 정수로 변환: {chat_id_to_use}")
            except (ValueError, TypeError) as e:
                mlog.error(f"chat_id를 정수로 변환 실패: {chat_id_to_use}, 에러: {e}")
                return
        
        # message_id가 정수인지 확인하고 변환
        if not isinstance(message_id, int):
            try:
                message_id = int(message_id)
                mlog.info(f"message_id를 정수로 변환: {message_id}")
            except (ValueError, TypeError) as e:
                mlog.error(f"message_id를 정수로 변환 실패: {message_id}, 에러: {e}")
                return
        
        mlog.debug(f"저장할 메시지 정보: chat_id={chat_id_to_use}, message_id={message_id}, is_forward={is_forward}")
        
        store.insert_message(
            chat_id=chat_id_to_use,
            message_id=message_id,
            date_ts=now_ts,
            author=author,
            text=text,
            original_text=raw_for_snippet,  # 원본 텍스트 추가
            forward_text="",  # 포워드 텍스트 (기본값)
            image_paths="[]",  # 이미지 경로들 (기본값)
            forward_info="{}",  # 포워드 정보 (기본값)
            embedding_value=embedding_json,
            text_hash=text_hash,
        )

        # LLM analysis
        try:
            analysis = llm.analyze(text)
            
            # 코인 관련성 체크
            if not analysis.is_coin_related:
                mlog.info(f"❌ 메시지 버림: 코인과 관련없음 (chat_id={chat_id}, msg_id={msg.id}) - {analysis.relevance_reason}")
                return
                
            mlog.info(f"코인 관련성 확인: {analysis.is_coin_related} - {analysis.relevance_reason}")
            
            # 정보 가치 체크
            if not analysis.has_valuable_info:
                mlog.info(f"❌ 메시지 버림: 정보 가치 없음 (chat_id={chat_id}, msg_id={msg.id}) - {analysis.info_value_reason}")
                return
                
            mlog.info(f"정보 가치 확인: {analysis.has_valuable_info} - {analysis.info_value_reason}")
            
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
        
        # 내용 없는 요약 필터링
        meaningless_summary_patterns = [
            r'구체적인 내용이 부족',
            r'요약하기 어렵습니다',
            r'추가적인 정보나 문맥이 필요',
            r'요약할 수 있는 구체적인 내용이 없',
            r'내용이 부족하여 요약하기 어렵',
            r'구체적인 정보가 부족',
            r'요약할 만한 내용이',
            r'추가 정보가 필요합니다',
            r'문맥이 부족',
            r'구체적인 내용이 없습니다',
            r'요약하기 어려운 내용입니다',
            r'추가적인 내용이나 맥락이 부족'
        ]
        
        is_meaningless_summary = any(re.search(pattern, analysis.summary, re.IGNORECASE) for pattern in meaningless_summary_patterns)
        
        if is_meaningless_summary:
            should_forward = False
            mlog.info(f"❌ 내용 없는 요약 차단: {analysis.summary[:100]}...")
        
        if not should_forward:
            # Store analysis but do not forward
            store.update_analysis(
                chat_id=chat_id,
                message_id=message_id,
                importance=analysis.importance,
                categories=",".join(analysis.categories),
                tags=",".join(analysis.tags),
                summary=analysis.summary,
                money_making_info=analysis.money_making_info,
                action_guide=analysis.action_guide,
                event_products=analysis.event_products,
                original_link=orig_link,
            )
            mlog.info(f"❌ 메시지 버림: 중요도 부족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} < {settings.important_threshold}, 텍스트 길이: {len(text)}자)")
            return

        # Forward to aggregator channel
        mlog.info(f"✅ 전달 승인: 중요도 충족 (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance} >= {settings.important_threshold})")
        
        # 메시지 작성시간 정보 수집
        try:
            # 현재 메시지 작성시간
            current_message_time = None
            if hasattr(msg, 'date') and msg.date:
                current_message_time = msg.date
            
            # 원본 메시지 작성시간 (포워드인 경우)
            original_message_time = None
            if is_forward and hasattr(msg, 'forward') and msg.forward:
                if hasattr(msg.forward, 'date') and msg.forward.date:
                    original_message_time = msg.forward.date
            
            # 시간 정보 포맷팅
            current_time_str = format_time(current_message_time)
            original_time_str = format_time(original_message_time)
        except Exception as e:
            mlog.warning(f"시간 정보 처리 실패: {e}")
            current_time_str = None
            original_time_str = None
        
        # 포워드 정보 준비
        forward_info = None
        if is_forward and original_chat_id:
            forward_channel_meta = await get_channel_meta(chat_id)
            original_channel_meta = await get_channel_meta(original_chat_id)
            forward_info = {
                "forward_channel": f"{forward_channel_meta.get('title', 'Unknown')} (@{forward_channel_meta.get('username', 'N/A')})",
                "original_channel": f"{original_channel_meta.get('title', 'Unknown')} (@{original_channel_meta.get('username', 'N/A')})",
                "current_time": current_time_str,
                "original_time": original_time_str
            }
        else:
            # 일반 메시지인 경우에도 시간 정보 포함
            forward_info = {
                "current_time": current_time_str
            }
        
        html = format_html(
            source_title=source_title,
            summary=analysis.summary,
            importance=analysis.importance,
            categories=analysis.categories,
            tags=analysis.tags,
            money_making_info=analysis.money_making_info,
            action_guide=analysis.action_guide,
            event_products=analysis.event_products,
            original_link=orig_link,
            image_content=image_content,
            link_content=link_content,
            forward_info=forward_info,
            original_snippet=(raw_for_snippet[:400] + ("…" if len(raw_for_snippet) > 400 else "")) if raw_for_snippet else None,
            extracted_links=extracted_links,
        )
        try:
            # 기본 채널로 전송
            await tg.send_html(settings.aggregator_channel, html)
            mlog.info(f"✅ 전송 성공: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) → {settings.aggregator_channel}")
            
            # high 중요도인 경우 중요 채널로도 중복 전송
            should_send_to_important = (
                analysis.importance == "high" or analysis.importance == "medium"
            )
            
            if should_send_to_important:
                try:
                    await tg.send_html(settings.important_channel, html)
                    mlog.info(f"🔥 중요 채널 전송 성공: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) → {settings.important_channel}")
                except Exception as e:
                    mlog.error(f"❌ 중요 채널 전송 실패: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) → {settings.important_channel} - {e}")
            
            # 봇 개인 알림 전송 (모든 전송된 메시지에 대해)
            try:
                # 채널과 동일한 포매팅 사용
                personal_html = format_html(
                    source_title=source_title,
                    summary=analysis.summary,
                    importance=analysis.importance,
                    categories=analysis.categories,
                    tags=analysis.tags,
                    money_making_info=analysis.money_making_info,
                    action_guide=analysis.action_guide,
                    event_products=analysis.event_products,
                    original_link=orig_link,
                    image_content=image_content,
                    link_content=link_content,
                    forward_info=forward_info,
                    original_snippet=(raw_for_snippet[:400] + ("…" if len(raw_for_snippet) > 400 else "")) if raw_for_snippet else None,
                    extracted_links=extracted_links,
                )
                
                if await bot_notifier.send_personal_html(personal_html):
                    mlog.info(f"📱 봇 개인 알림 전송 성공: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id})")
                else:
                    mlog.warning(f"⚠️ 봇 개인 알림 전송 실패: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id})")
                
                # 중요 봇 알림 (medium 이상 + 돈버는 정보)
                is_important = (
                    analysis.importance in ["medium", "high"]
                )
                
                if is_important and bot_notifier.important_bot_token:
                    try:
                        if await bot_notifier.send_important_html(personal_html):
                            mlog.info(f"🔥 중요 봇 알림 전송 성공: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id})")
                        else:
                            mlog.warning(f"⚠️ 중요 봇 알림 전송 실패: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id})")
                    except Exception as e:
                        mlog.error(f"❌ 중요 봇 알림 전송 오류: {e}")
            except Exception as e:
                mlog.error(f"❌ 봇 개인 알림 전송 오류: {e}")
            
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
            event_products=analysis.event_products,
            original_link=orig_link,
        )
        
        # 돈버는 정보가 있는 메시지는 별도 저장
        if analysis.money_making_info and analysis.money_making_info != "없음":
            try:
                # 이미지 경로 수집
                image_paths = []
                if has_media and image_content:
                    for img in image_content:
                        if 'path' in img:
                            image_paths.append(img['path'])
                
                # 포워딩 텍스트 준비
                forward_text = ""
                if is_forward and forward_info:
                    forward_text = forward_info.get('text', '')
                
                store.save_money_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    date_ts=now_ts,
                    author=author,
                    original_text=raw_for_snippet,
                    forward_text=forward_text,
                    money_making_info=analysis.money_making_info,
                    action_guide=analysis.action_guide,
                    event_products=analysis.event_products,
                    image_paths=image_paths,
                    forward_info=forward_info or {},
                    original_link=orig_link,
                    importance=analysis.importance,
                    categories=",".join(analysis.categories),
                    tags=",".join(analysis.tags),
                    summary=analysis.summary,
                )
                mlog.info(f"💰 돈버는 정보 메시지 별도 저장: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id})")
            except Exception as e:
                mlog.error(f"❌ 돈버는 정보 메시지 저장 실패: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}) - {e}")
        forward_log = f" [FORWARD from {original_chat_id}:{original_message_id}]" if is_forward else ""
        mlog.info(f"✅ 메시지 처리 완료: {meta.get('title','Unknown')} (chat_id={chat_id}, msg_id={message_id}, importance={analysis.importance}){forward_log}")

    # 폴링 방식만 사용 (이벤트 리스너 제거로 중복 처리 방지)
    logger.info("폴링 방식만 사용하여 메시지 중복 처리 방지")
    
    # 채널 접근 권한 테스트
    async def test_channel_access():
        logger.info("=== 채널 접근 권한 테스트 시작 ===")
        for channel_id in chat_filters:
            try:
                # 채널 정보 가져오기 시도
                chat = await tg.client.get_entity(channel_id)
                # 안전한 채널 제목 접근
                channel_title = getattr(chat, 'title', f'Channel {channel_id}')
                logger.info(f"✅ 채널 접근 가능: {channel_title} (ID: {channel_id})")
                
                # 최근 메시지 가져오기 시도 (권한 확인)
                try:
                    messages = await tg.client.get_messages(chat, limit=1)
                    if messages:
                        logger.info(f"✅ 메시지 읽기 권한 있음: {channel_title} (최근 메시지 ID: {messages[0].id})")
                    else:
                        logger.info(f"⚠️ 메시지 없음: {channel_title}")
                except Exception as e:
                    logger.warning(f"❌ 메시지 읽기 권한 없음: {channel_title} - {e}")
                    
            except Exception as e:
                logger.error(f"❌ 채널 접근 불가: ID {channel_id} - {e}")
        
        logger.info("=== 채널 접근 권한 테스트 완료 ===")
    
    # 채널 접근 테스트 실행
    await test_channel_access()
    
    # 폴링 방식으로 메시지 수신 (실시간 수신 대안)
    async def poll_messages():
        logger.info("=== 폴링 방식 메시지 수신 시작 ===")
        
        # 초기화: 각 채널의 마지막 처리된 메시지 ID를 데이터베이스에서 가져오기
        # 기존 채널들의 마지막 메시지 ID 로드 (안전하게)
        try:
            last_message_ids = store.get_all_channel_last_message_ids()
        except Exception as e:
            logger.warning(f"채널 마지막 메시지 ID 로드 실패: {e}")
            last_message_ids = {}
        
        # 재시작 시 모든 모니터링 채널을 현재 최신 메시지 ID로 초기화하여 백필 방지
        for channel_id in chat_filters:
            try:
                chat = entity_cache.get(channel_id)
                if not chat:
                    chat = await tg.client.get_entity(channel_id)
                    if chat:
                        entity_cache[channel_id] = chat
                
                latest_id = 0
                if chat:
                    messages = await tg.client.get_messages(chat, limit=1)
                    if messages:
                        latest_id = messages[0].id
                
                last_message_ids[channel_id] = latest_id
                store.update_channel_last_message_id(channel_id, latest_id)
                logger.info(f"채널 {channel_id} 최신 메시지 ID 초기화: {latest_id}")
            except Exception as e:
                logger.warning(f"채널 {channel_id} 초기화 실패: {e}")
        
        # 기존 채널들의 마지막 메시지 ID 로깅
        for channel_id, last_id in last_message_ids.items():
            if channel_id in chat_filters:
                logger.info(f"채널 {channel_id} 마지막 메시지 ID: {last_id}")
        
        while True:
            try:
                # SOURCE_CHANNELS 최신화 후 숫자 ID로 정규화
                raw_updated_chat_filters = load_source_channels()
                normalized_updated_chat_filters = []
                for ch in raw_updated_chat_filters:
                    if ch in removed_channels:
                        continue
                    try:
                        # 엔티티를 가져와 숫자 ID로 변환
                        ent = await tg.client.get_entity(ch)
                        if (hasattr(ent, 'id') and not isinstance(ent, str) and hasattr(ent, '__class__')):
                            numeric_id = utils.get_peer_id(ent)
                            # 엔티티 캐시 업데이트
                            entity_cache[numeric_id] = ent
                            normalized_updated_chat_filters.append(numeric_id)
                        else:
                            logger.warning(f"유효하지 않은 엔티티 타입: {type(ent)} (채널: {ch})")
                    except Exception as e:
                        logger.warning(f"채널 정규화 실패: {ch} - {e}")
                        continue

                if normalized_updated_chat_filters != chat_filters:
                    logger.info(f"🔄 SOURCE_CHANNELS 업데이트 감지: {len(chat_filters)} → {len(normalized_updated_chat_filters)}")
                    new_channels = set(normalized_updated_chat_filters) - set(chat_filters)
                    if new_channels:
                        logger.info(f"새로운 채널: {new_channels}")
                    else:
                        logger.info(f"제거된 채널이 다시 로딩되어 필터링됨: {removed_channels}")

                    # 새로운 채널들의 최신 메시지 ID를 현재 최신으로 초기화하여 백필 처리 방지
                    for new_channel_id in new_channels:
                        try:
                            chat = entity_cache.get(new_channel_id)
                            if not chat:
                                chat = await tg.client.get_entity(new_channel_id)
                                if chat:
                                    entity_cache[new_channel_id] = chat

                            latest_id = 0
                            if chat:
                                msgs = await tg.client.get_messages(chat, limit=1)
                                if msgs:
                                    latest_id = msgs[0].id

                            last_message_ids[new_channel_id] = latest_id
                            store.update_channel_last_message_id(new_channel_id, latest_id)
                            logger.info(f"새 채널 {new_channel_id} 최신 메시지 ID 초기화: {latest_id}")
                        except Exception as e:
                            logger.warning(f"새 채널 {new_channel_id} 초기화 실패: {e}")

                    chat_filters.clear()
                    chat_filters.extend(normalized_updated_chat_filters)
                
                for channel_id in chat_filters:
                    try:
                        # 채널 정보 가져오기 (엔티티 캐시 활용)
                        chat = entity_cache.get(channel_id)
                        if not chat:
                            # 엔티티 캐시에 없으면 새로 가져오기
                            chat = await tg.client.get_entity(channel_id)
                            if not chat:
                                logger.warning(f"채널 정보를 가져올 수 없음: {channel_id}")
                                continue
                            # 엔티티 캐시에 저장
                            entity_cache[channel_id] = chat
                        
                        # 마지막 처리된 메시지 ID 이후의 메시지만 가져오기
                        last_known_id = last_message_ids.get(channel_id, 0)
                        messages = await tg.client.get_messages(chat, min_id=last_known_id, limit=50)
                        
                        if not messages:
                            continue
                            
                        # 새로운 메시지가 있는지 확인
                        if messages:
                            # 안전한 채널 제목 접근
                            channel_title = getattr(chat, 'title', f'Channel {channel_id}')
                            logger.info(f"🔍 폴링으로 새 메시지 발견: {channel_title} ({len(messages)}개)")
                            
                            # 새로운 메시지들 처리 (ID 순서대로)
                            for msg in messages:
                                # 이미 처리된 메시지인지 한번 더 확인
                                if not store.is_message_processed(channel_id, msg.id):
                                    # 메시지를 이벤트 객체로 래핑하여 handle_message 호출
                                    try:
                                        # 메시지 객체를 이벤트 객체로 래핑
                                        class EventWrapper:
                                            def __init__(self, message, chat_id):
                                                self.message = message
                                                self.chat_id = chat_id
                                                self.chat = None
                                        
                                        # 폴링 메시지의 경우 chat_id가 이미 숫자 ID이므로 numeric_chat_id로 설정
                                        numeric_chat_id = channel_id
                                        
                                        event = EventWrapper(msg, numeric_chat_id)
                                        await handle_message(event)
                                        
                                        # 처리 완료 후 DB에 기록 (중복 방지)
                                        store.mark_message_processed(channel_id, msg.id)
                                        logger.info(f"✅ 폴링 메시지 처리 완료: {channel_title} (ID: {msg.id})")
                                    except Exception as e:
                                        logger.error(f"❌ 폴링 메시지 처리 실패: {channel_title} (ID: {msg.id}) - {e}")
                                        # 실패한 메시지도 DB에 기록하여 재시도 방지
                                        store.mark_message_processed(channel_id, msg.id)
                                else:
                                    logger.debug(f"⏭️ 이미 처리된 메시지 건너뜀: {channel_title} (ID: {msg.id})")
                            
                            # 마지막 메시지 ID 업데이트 (DB에 저장)
                            if messages:
                                latest_message_id = max(msg.id for msg in messages)
                                last_message_ids[channel_id] = latest_message_id
                                store.update_channel_last_message_id(channel_id, latest_message_id)
                                logger.info(f"채널 {channel_id} 최신 메시지 ID 업데이트: {latest_message_id}")
                            
                    except Exception as e:
                        logger.warning(f"폴링 중 오류 (채널 {channel_id}): {e}")
                        # 채널 접근 실패 시 일정 시간 대기
                        await asyncio.sleep(5)
                
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
    logger.info(f"폴링 방식 메시지 수신 대기 중")
    
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
                
                # 캐시 상태 확인
                logger.info(f"캐시 상태: 메타데이터 {len(channel_cache)}개, 엔티티 {len(entity_cache)}개")
                
                # 캐시 정리
                clear_old_cache()
                
            except Exception as e:
                logger.error(f"통계 출력 실패: {e}")
    
    # 통계 출력 태스크 시작
    asyncio.create_task(print_stats())
    
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())


