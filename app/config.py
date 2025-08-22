from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session: str
    source_channels: List[str]
    aggregator_channel: str
    important_channel: str
    
    # 봇 설정
    bot_token: str
    personal_chat_id: str
    important_bot_token: str

    openai_api_key: str
    openai_model: str
    upstage_api_key: str

    important_threshold: str
    dedup_similarity_threshold: float
    dedup_recent_minutes: int

    sqlite_path: str


def load_settings() -> Settings:
    load_dotenv()

    telegram_api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH", "")
    telegram_session = os.getenv("TELEGRAM_SESSION", "telegram_session")

    source_channels_raw = os.getenv("SOURCE_CHANNELS", "").strip()
    source_channels = [s.strip() for s in source_channels_raw.split(",") if s.strip()]

    aggregator_channel = os.getenv("AGGREGATOR_CHANNEL", "me").strip()
    important_channel = os.getenv("IMPORTANT_CHANNEL", "@arang_summary_important").strip()

    # 봇 설정
    bot_token = os.getenv("BOT_TOKEN", "")
    personal_chat_id = os.getenv("PERSONAL_CHAT_ID", "")
    important_bot_token = os.getenv("IMPORTANT_BOT_TOKEN", "")

    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    upstage_api_key = os.getenv("UPSTAGE_API_KEY", "")

    important_threshold = os.getenv("IMPORTANT_THRESHOLD", "low").lower()
    dedup_similarity_threshold = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.85"))
    dedup_recent_minutes = int(os.getenv("DEDUP_RECENT_MINUTES", "360"))

    sqlite_path = os.getenv("SQLITE_PATH", "data/db.sqlite3")

    return Settings(
        telegram_api_id=telegram_api_id,
        telegram_api_hash=telegram_api_hash,
        telegram_session=telegram_session,
        source_channels=source_channels,
        aggregator_channel=aggregator_channel,
        important_channel=important_channel,
        bot_token=bot_token,
        personal_chat_id=personal_chat_id,
        important_bot_token=important_bot_token,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        upstage_api_key=upstage_api_key,
        important_threshold=important_threshold,
        dedup_similarity_threshold=dedup_similarity_threshold,
        dedup_recent_minutes=dedup_recent_minutes,
        sqlite_path=sqlite_path,
    )


def load_source_channels() -> List[str]:
    """SOURCE_CHANNELS를 동적으로 로드합니다."""
    load_dotenv()
    source_channels_raw = os.getenv("SOURCE_CHANNELS", "").strip()
    return [s.strip() for s in source_channels_raw.split(",") if s.strip()]


async def get_channel_username_async(channel_id: str, tg_client=None) -> Optional[str]:
    """Telegram API를 사용하여 채널 ID를 @username으로 변환합니다."""
    try:
        # 이미 @username 형태인 경우 그대로 반환
        if channel_id.startswith("@"):
            return channel_id
        
        # 숫자 ID인 경우 Telegram API로 변환 시도
        if channel_id.startswith("-100") and tg_client:
            try:
                entity = await tg_client.get_entity(int(channel_id))
                if hasattr(entity, 'username') and entity.username:
                    return f"@{entity.username}"
                else:
                    # username이 없는 경우 숫자 ID 반환
                    return channel_id
            except Exception as e:
                print(f"Telegram API 변환 실패: {e}")
                return channel_id
        
        return channel_id
        
    except Exception as e:
        print(f"채널 ID 변환 실패: {e}")
        return channel_id


def get_channel_username(channel_id: str) -> Optional[str]:
    """채널 ID를 @username으로 변환합니다. (동기 버전)"""
    try:
        # 이미 @username 형태인 경우 그대로 반환
        if channel_id.startswith("@"):
            return channel_id
        
        # 숫자 ID인 경우 기본적으로 숫자 ID 반환
        # 실제 변환은 Telegram API를 통해 수행해야 하지만,
        # 설정 파일에서는 숫자 ID를 그대로 사용하는 것이 안전함
        return channel_id
        
    except Exception as e:
        print(f"채널 ID 변환 실패: {e}")
        return channel_id


def add_source_channel(channel_id: str) -> bool:
    """새로운 채널을 SOURCE_CHANNELS에 추가합니다."""
    import re
    
    # .env 파일 경로
    env_path = ".env"
    
    try:
        # 현재 .env 파일 읽기
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # SOURCE_CHANNELS 라인 찾기
        source_channels_line_index = None
        for i, line in enumerate(lines):
            if line.strip().startswith("SOURCE_CHANNELS="):
                source_channels_line_index = i
                break
        
        if source_channels_line_index is not None:
            # 기존 SOURCE_CHANNELS 라인 업데이트
            current_line = lines[source_channels_line_index]
            current_channels = current_line.split("=", 1)[1].strip()
            
            # 채널 ID가 이미 있는지 확인 (숫자 ID와 @username 모두 체크)
            channel_list = [s.strip() for s in current_channels.split(",") if s.strip()]
            
            # 숫자 ID가 이미 있는지 확인
            if channel_id in channel_list:
                return False  # 이미 존재함
            
            # @username 형태로 변환 시도
            username_form = get_channel_username(channel_id)
            
            # @username 형태가 이미 있는지 확인
            if username_form in channel_list:
                return False  # 이미 존재함
            
            # 새 채널 추가 (@username 형태 우선)
            if current_channels:
                new_channels = f"{current_channels},{username_form}"
            else:
                new_channels = username_form
            
            lines[source_channels_line_index] = f"SOURCE_CHANNELS={new_channels}\n"
        else:
            # SOURCE_CHANNELS 라인이 없으면 새로 추가
            username_form = get_channel_username(channel_id)
            lines.append(f"SOURCE_CHANNELS={username_form}\n")
        
        # .env 파일 업데이트
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        return True
        
    except Exception as e:
        print(f"SOURCE_CHANNELS 업데이트 실패: {e}")
        return False


def remove_source_channel(channel_id: str) -> bool:
    """채널을 SOURCE_CHANNELS에서 제거합니다."""
    import re
    
    # .env 파일 경로
    env_path = ".env"
    
    try:
        # 현재 .env 파일 읽기
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # SOURCE_CHANNELS 라인 찾기
        source_channels_line_index = None
        for i, line in enumerate(lines):
            if line.strip().startswith("SOURCE_CHANNELS="):
                source_channels_line_index = i
                break
        
        if source_channels_line_index is None:
            return False  # SOURCE_CHANNELS 라인이 없음
        
        # 기존 SOURCE_CHANNELS 라인 업데이트
        current_line = lines[source_channels_line_index]
        current_channels = current_line.split("=", 1)[1].strip()
        
        # 채널 ID가 있는지 확인
        if channel_id not in current_channels:
            return False  # 존재하지 않음
        
        # 채널 제거
        channel_list = [s.strip() for s in current_channels.split(",") if s.strip()]
        if channel_id in channel_list:
            channel_list.remove(channel_id)
        
        # 새로운 SOURCE_CHANNELS 라인 생성
        if channel_list:
            new_channels = ",".join(channel_list)
            lines[source_channels_line_index] = f"SOURCE_CHANNELS={new_channels}\n"
        else:
            # 모든 채널이 제거된 경우 빈 문자열로 설정
            lines[source_channels_line_index] = f"SOURCE_CHANNELS=\n"
        
        # .env 파일 업데이트
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        return True
        
    except Exception as e:
        print(f"SOURCE_CHANNELS 제거 실패: {e}")
        return False


