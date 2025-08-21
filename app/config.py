from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


@dataclass
class Settings:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session: str
    source_channels: List[str]
    aggregator_channel: str

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
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        upstage_api_key=upstage_api_key,
        important_threshold=important_threshold,
        dedup_similarity_threshold=dedup_similarity_threshold,
        dedup_recent_minutes=dedup_recent_minutes,
        sqlite_path=sqlite_path,
    )


