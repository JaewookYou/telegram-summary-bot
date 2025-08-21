from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Tuple
import logging


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
            
            # 기존 테이블이 있는지 확인
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            table_exists = c.fetchone() is not None
            
            if table_exists:
                # 기존 테이블의 simhash 컬럼 타입 확인
                c.execute("PRAGMA table_info(messages)")
                columns = c.fetchall()
                simhash_col = next((col for col in columns if col[1] == 'simhash'), None)
                
                if simhash_col and simhash_col[2] == 'INTEGER':
                    # simhash 컬럼을 TEXT로 변경
                    logger = logging.getLogger("app.storage")
                    logger.info("simhash 컬럼을 TEXT로 마이그레이션 중...")
                    
                    # 임시 테이블 생성
                    c.execute("""
                        CREATE TABLE messages_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            chat_id BIGINT NOT NULL,
                            message_id BIGINT NOT NULL,
                            date_ts INTEGER NOT NULL,
                            author TEXT,
                            text TEXT NOT NULL,
                            simhash TEXT NOT NULL,
                            importance TEXT,
                            categories TEXT,
                            tags TEXT,
                            summary TEXT,
                            original_link TEXT,
                            UNIQUE(chat_id, message_id)
                        )
                    """)
                    
                    # 데이터 복사 (simhash를 TEXT로 변환)
                    c.execute("""
                        INSERT INTO messages_new
                        SELECT id, chat_id, message_id, date_ts, author, text, 
                               CAST(simhash AS TEXT), importance, categories, tags, summary, original_link
                        FROM messages
                    """)
                    
                    # 기존 테이블 삭제 및 새 테이블 이름 변경
                    c.execute("DROP TABLE messages")
                    c.execute("ALTER TABLE messages_new RENAME TO messages")
                    
                    # 인덱스 재생성
                    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_date_ts ON messages(date_ts)")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_simhash ON messages(simhash)")
                    
                    logger.info("simhash 컬럼 마이그레이션 완료")
            else:
                # 새 테이블 생성
                c.execute(
                    """
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL,
                        date_ts INTEGER NOT NULL,
                        author TEXT,
                        text TEXT NOT NULL,
                        simhash TEXT NOT NULL,
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
        # 디버깅: 값 타입과 크기 확인
        logger = logging.getLogger("app.storage")
        logger.debug(f"insert_message 호출: chat_id={chat_id} (타입: {type(chat_id)}), message_id={message_id} (타입: {type(message_id)})")
        logger.debug(f"chat_id 크기: {chat_id.bit_length()} bits, message_id 크기: {message_id.bit_length()} bits")
        logger.debug(f"simhash_value 크기: {simhash_value.bit_length()} bits, 값: {simhash_value}")
        
        # simhash_value를 TEXT로 변환 (정확성 유지)
        simhash_text = str(simhash_value)
        
        # SQLite INTEGER 범위 확인 (chat_id, message_id만)
        max_sqlite_int = 2**63 - 1
        if chat_id > max_sqlite_int or message_id > max_sqlite_int:
            logger.error(f"SQLite INTEGER 범위 초과: chat_id={chat_id}, message_id={message_id}, 최대값={max_sqlite_int}")
            raise OverflowError(f"SQLite INTEGER 범위 초과: chat_id={chat_id}, message_id={message_id}")
        
        with self.connect() as conn:
            c = conn.cursor()
            try:
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
                        simhash_text,  # TEXT로 저장
                        importance,
                        categories,
                        tags,
                        summary,
                        original_link,
                    ),
                )
                conn.commit()
                logger.debug(f"메시지 저장 성공: chat_id={chat_id}, message_id={message_id}")
                return c.lastrowid
            except Exception as e:
                logger.error(f"메시지 저장 실패: chat_id={chat_id}, message_id={message_id}, 에러: {e}")
                raise

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
        for chat_id, message_id, simhash_text in rows:
            try:
                # TEXT로 저장된 simhash를 int로 변환
                simhash_int = int(simhash_text)
                if hamming(simhash_int, simhash_value) <= max_hamming:
                    best = (chat_id, message_id, simhash_int)
                    break
            except (ValueError, TypeError) as e:
                # 변환 실패 시 로그 기록하고 건너뛰기
                logger = logging.getLogger("app.storage")
                logger.warning(f"simhash 변환 실패: {simhash_text}, 에러: {e}")
                continue
        return best


