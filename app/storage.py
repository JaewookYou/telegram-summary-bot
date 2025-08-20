from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Tuple


@dataclass
class MessageRecord:
    id: int
    chat_id: int
    message_id: int
    date_ts: int
    author: Optional[str]
    text: str
    simhash: int
    importance: str
    categories: str
    tags: str
    summary: str
    original_link: str


class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    date_ts INTEGER NOT NULL,
                    author TEXT,
                    text TEXT NOT NULL,
                    simhash INTEGER NOT NULL,
                    importance TEXT,
                    categories TEXT,
                    tags TEXT,
                    summary TEXT,
                    original_link TEXT,
                    UNIQUE(chat_id, message_id)
                )
                """
            )
            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_date_ts ON messages(date_ts);
                """
            )
            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_simhash ON messages(simhash);
                """
            )
            conn.commit()

    def insert_message(
        self,
        chat_id: int,
        message_id: int,
        date_ts: int,
        author: Optional[str],
        text: str,
        simhash_value: int,
        importance: Optional[str] = None,
        categories: Optional[str] = None,
        tags: Optional[str] = None,
        summary: Optional[str] = None,
        original_link: Optional[str] = None,
    ) -> int:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT OR IGNORE INTO messages (
                    chat_id, message_id, date_ts, author, text, simhash, importance, categories, tags, summary, original_link
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    date_ts,
                    author,
                    text,
                    simhash_value,
                    importance,
                    categories,
                    tags,
                    summary,
                    original_link,
                ),
            )
            conn.commit()
            return c.lastrowid

    def update_analysis(
        self,
        chat_id: int,
        message_id: int,
        importance: str,
        categories: str,
        tags: str,
        summary: str,
        original_link: str,
    ) -> None:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE messages
                SET importance = ?, categories = ?, tags = ?, summary = ?, original_link = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (importance, categories, tags, summary, original_link, chat_id, message_id),
            )
            conn.commit()

    def find_recent_similar(
        self, simhash_value: int, since_ts: int, max_hamming: int
    ) -> Optional[Tuple[int, int, int]]:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT chat_id, message_id, simhash
                FROM messages
                WHERE date_ts >= ?
                ORDER BY date_ts DESC
                LIMIT 1000
                """,
                (since_ts,),
            )
            rows = c.fetchall()

        def hamming(a: int, b: int) -> int:
            return (a ^ b).bit_count()

        best: Optional[Tuple[int, int, int]] = None
        for chat_id, message_id, sim in rows:
            if hamming(sim, simhash_value) <= max_hamming:
                best = (chat_id, message_id, sim)
                break
        return best


