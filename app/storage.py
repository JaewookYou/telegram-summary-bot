from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Tuple
import logging

logger = logging.getLogger("app.storage")


@dataclass
class MessageRecord:
    id: int
    chat_id: int
    message_id: int
    date_ts: int
    author: Optional[str]
    text: str
    embedding: str  # JSON 형태의 임베딩 벡터
    importance: str
    categories: str
    tags: str
    summary: str
    money_making_info: str
    action_guide: str
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
                # 기존 테이블의 컬럼 확인
                c.execute("PRAGMA table_info(messages)")
                columns = c.fetchall()
                column_names = [col[1] for col in columns]
                
                # simhash 컬럼이 있으면 embedding으로 변경
                if 'simhash' in column_names:
                    logger.info("기존 simhash 컬럼을 embedding으로 변경 중...")
                    c.execute("ALTER TABLE messages RENAME COLUMN simhash TO embedding")
                    c.execute("UPDATE messages SET embedding = '[]' WHERE embedding IS NULL OR embedding = ''")
                
                # embedding 컬럼이 없으면 추가
                if 'embedding' not in column_names:
                    logger.info("embedding 컬럼 추가 중...")
                    c.execute("ALTER TABLE messages ADD COLUMN embedding TEXT DEFAULT '[]'")
                
                # money_making_info 컬럼이 없으면 추가
                if 'money_making_info' not in column_names:
                    logger.info("money_making_info 컬럼 추가 중...")
                    c.execute("ALTER TABLE messages ADD COLUMN money_making_info TEXT DEFAULT ''")
                
                # action_guide 컬럼이 없으면 추가
                if 'action_guide' not in column_names:
                    logger.info("action_guide 컬럼 추가 중...")
                    c.execute("ALTER TABLE messages ADD COLUMN action_guide TEXT DEFAULT ''")
            else:
                # 새 테이블 생성
                c.execute("""
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        date_ts INTEGER NOT NULL,
                        author TEXT,
                        text TEXT NOT NULL,
                        embedding TEXT NOT NULL DEFAULT '[]',
                        importance TEXT NOT NULL,
                        categories TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        money_making_info TEXT NOT NULL DEFAULT '',
                        action_guide TEXT NOT NULL DEFAULT '',
                        original_link TEXT NOT NULL,
                        UNIQUE(chat_id, message_id)
                    )
                """)
                c.execute("CREATE INDEX idx_messages_date_ts ON messages(date_ts)")
                c.execute("CREATE INDEX idx_messages_chat_id ON messages(chat_id)")
                c.execute("CREATE INDEX idx_messages_importance ON messages(importance)")
            
            conn.commit()
            
            conn.commit()

    def insert_message(
        self,
        chat_id: int,
        message_id: int,
        date_ts: int,
        author: Optional[str],
        text: str,
        embedding_value: str,  # JSON 형태의 임베딩 벡터
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
                        chat_id, message_id, date_ts, author, text, embedding, importance, categories, tags, summary, original_link
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        message_id,
                        date_ts,
                        author,
                        text,
                        embedding_value,  # JSON 형태의 임베딩 벡터
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
        money_making_info: str,
        action_guide: str,
        original_link: str,
    ) -> None:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE messages 
                SET importance = ?, categories = ?, tags = ?, summary = ?, money_making_info = ?, action_guide = ?, original_link = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (importance, categories, tags, summary, money_making_info, action_guide, original_link, chat_id, message_id),
            )
            conn.commit()

    def find_recent_similar(
        self, embedding_value: str, since_ts: int, similarity_threshold: float, embedding_client
    ) -> Optional[Tuple[int, int, float]]:
        """임베딩 벡터를 사용하여 유사한 메시지를 찾습니다."""
        import json
        
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT chat_id, message_id, embedding
                FROM messages
                WHERE date_ts >= ? AND embedding != '[]'
                ORDER BY date_ts DESC
                LIMIT 1000
                """,
                (since_ts,),
            )
            rows = c.fetchall()

        try:
            current_embedding = json.loads(embedding_value)
        except (ValueError, TypeError) as e:
            logger = logging.getLogger("app.storage")
            logger.error(f"현재 임베딩 파싱 실패: {e}")
            return None

        best: Optional[Tuple[int, int, float]] = None
        best_similarity = 0.0
        
        for chat_id, message_id, stored_embedding_json in rows:
            try:
                # 저장된 임베딩 벡터 파싱
                stored_embedding = json.loads(stored_embedding_json)
                
                # 코사인 유사도 계산
                similarity = embedding_client.cosine_similarity(current_embedding, stored_embedding)
                
                if similarity >= similarity_threshold and similarity > best_similarity:
                    best = (chat_id, message_id, similarity)
                    best_similarity = similarity
                    
            except (ValueError, TypeError) as e:
                # 파싱 실패 시 로그 기록하고 건너뛰기
                logger = logging.getLogger("app.storage")
                logger.warning(f"저장된 임베딩 파싱 실패: {stored_embedding_json}, 에러: {e}")
                continue
                
        return best

    def get_message_count(self) -> int:
        """총 메시지 개수를 반환"""
        with self.connect() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM messages")
            return c.fetchone()[0]

    def get_importance_stats(self) -> dict:
        """중요도별 메시지 통계를 반환"""
        with self.connect() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT importance, COUNT(*) as count 
                FROM messages 
                WHERE importance IS NOT NULL 
                GROUP BY importance 
                ORDER BY count DESC
            """)
            rows = c.fetchall()
            return {row[0]: row[1] for row in rows}

    def get_recent_message_count(self, seconds: int) -> int:
        """최근 N초 내 메시지 개수를 반환"""
        with self.connect() as conn:
            c = conn.cursor()
            current_ts = int(datetime.utcnow().timestamp())
            since_ts = current_ts - seconds
            c.execute("SELECT COUNT(*) FROM messages WHERE date_ts >= ?", (since_ts,))
            return c.fetchone()[0]


