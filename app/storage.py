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
    text_hash: str  # 원본 텍스트의 해시값 (중복 제거용)
    importance: str
    categories: str
    tags: str
    summary: str
    money_making_info: str
    action_guide: str
    event_products: str
    original_link: str


@dataclass
class MoneyMessageRecord:
    id: int
    chat_id: int
    message_id: int
    date_ts: int
    author: Optional[str]
    text: str  # 텍스트
    original_text: str  # 원문 텍스트
    forward_text: str   # 포워딩된 경우 포워딩 텍스트
    money_making_info: str
    action_guide: str
    event_products: str
    image_paths: str    # JSON 형태의 이미지 경로들
    forward_info: str   # JSON 형태의 포워딩 정보
    original_link: str
    importance: str
    categories: str
    tags: str
    summary: str


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
            
            # 스키마 버전 확인 및 마이그레이션
            table_exists = self._migrate_schema(c, table_exists)
            
            # 강제로 테이블 재생성 (datatype mismatch 문제 해결을 위해)
            if table_exists:
                logger.warning("datatype mismatch 문제 해결을 위해 테이블을 강제로 재생성합니다.")
                try:
                    c.execute("DROP TABLE IF EXISTS messages")
                    c.execute("DROP TABLE IF EXISTS money_messages")
                    table_exists = False
                    logger.info("기존 테이블 삭제 완료")
                except Exception as e:
                    logger.error(f"테이블 삭제 중 오류: {e}")
                    table_exists = False
            
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
                
                # event_products 컬럼이 없으면 추가
                if 'event_products' not in column_names:
                    logger.info("event_products 컬럼 추가 중...")
                    c.execute("ALTER TABLE messages ADD COLUMN event_products TEXT DEFAULT ''")
                
                # text_hash 컬럼이 없으면 추가
                if 'text_hash' not in column_names:
                    logger.info("text_hash 컬럼 추가 중...")
                    c.execute("ALTER TABLE messages ADD COLUMN text_hash TEXT DEFAULT ''")
            
            # money_messages 테이블 생성 (돈버는 정보 메시지 전용)
            c.execute("""
                CREATE TABLE IF NOT EXISTS money_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    date_ts INTEGER NOT NULL,
                    author TEXT,
                    text TEXT NOT NULL DEFAULT '',
                    original_text TEXT NOT NULL,
                    forward_text TEXT NOT NULL DEFAULT '',
                    money_making_info TEXT NOT NULL,
                    action_guide TEXT NOT NULL DEFAULT '',
                    event_products TEXT NOT NULL DEFAULT '',
                    image_paths TEXT NOT NULL DEFAULT '[]',
                    forward_info TEXT NOT NULL DEFAULT '{}',
                    embedding TEXT NOT NULL DEFAULT '[]',
                    text_hash TEXT NOT NULL DEFAULT '',
                    original_link TEXT NOT NULL DEFAULT '',
                    importance TEXT NOT NULL,
                    categories TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    UNIQUE(chat_id, message_id)
                )
            """)
            
            # money_messages 테이블 마이그레이션
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='money_messages'")
            money_table_exists = c.fetchone() is not None
            
            if money_table_exists:
                # money_messages 테이블의 컬럼 확인
                c.execute("PRAGMA table_info(money_messages)")
                money_columns = c.fetchall()
                money_column_names = [col[1] for col in money_columns]
                
                # text 컬럼이 없으면 추가
                if 'text' not in money_column_names:
                    try:
                        c.execute("ALTER TABLE money_messages ADD COLUMN text TEXT NOT NULL DEFAULT ''")
                        logger.info("money_messages 테이블에 text 컬럼 추가됨")
                    except Exception as e:
                        if "duplicate column name" not in str(e).lower():
                            logger.warning(f"text 컬럼 추가 실패: {e}")
                
                # embedding 컬럼이 없으면 추가
                if 'embedding' not in money_column_names:
                    try:
                        c.execute("ALTER TABLE money_messages ADD COLUMN embedding TEXT NOT NULL DEFAULT '[]'")
                        logger.info("money_messages 테이블에 embedding 컬럼 추가됨")
                    except Exception as e:
                        if "duplicate column name" not in str(e).lower():
                            logger.warning(f"embedding 컬럼 추가 실패: {e}")
                
                # text_hash 컬럼이 없으면 추가
                if 'text_hash' not in money_column_names:
                    try:
                        c.execute("ALTER TABLE money_messages ADD COLUMN text_hash TEXT NOT NULL DEFAULT ''")
                        logger.info("money_messages 테이블에 text_hash 컬럼 추가됨")
                    except Exception as e:
                        if "duplicate column name" not in str(e).lower():
                            logger.warning(f"text_hash 컬럼 추가 실패: {e}")
            
            # money_messages 테이블 인덱스 생성
            c.execute("CREATE INDEX IF NOT EXISTS idx_money_messages_date_ts ON money_messages(date_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_money_messages_chat_id ON money_messages(chat_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_money_messages_importance ON money_messages(importance)")
            
            # 채널별 최신 메시지 ID 추적 테이블 생성
            c.execute("""
                CREATE TABLE IF NOT EXISTS channel_last_message_ids (
                    chat_id INTEGER PRIMARY KEY,
                    last_message_id INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            
            if not table_exists:
                # 새 테이블 생성
                c.execute("""
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        date_ts INTEGER NOT NULL,
                        author TEXT,
                        text TEXT NOT NULL,
                        original_text TEXT NOT NULL DEFAULT '',
                        forward_text TEXT NOT NULL DEFAULT '',
                        image_paths TEXT NOT NULL DEFAULT '[]',
                        forward_info TEXT NOT NULL DEFAULT '{}',
                        embedding TEXT NOT NULL DEFAULT '[]',
                        importance TEXT NOT NULL,
                        categories TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        money_making_info TEXT NOT NULL DEFAULT '',
                        action_guide TEXT NOT NULL DEFAULT '',
                        event_products TEXT NOT NULL DEFAULT '',
                        text_hash TEXT NOT NULL DEFAULT '',
                        original_link TEXT NOT NULL,
                        UNIQUE(chat_id, message_id)
                    )
                """)
                c.execute("CREATE INDEX idx_messages_date_ts ON messages(date_ts)")
                c.execute("CREATE INDEX idx_messages_chat_id ON messages(chat_id)")
                c.execute("CREATE INDEX idx_messages_importance ON messages(importance)")
            else:
                # 기존 테이블에 original_text 컬럼 추가 (마이그레이션)
                try:
                    c.execute("ALTER TABLE messages ADD COLUMN original_text TEXT NOT NULL DEFAULT ''")
                    logger.info("messages 테이블에 original_text 컬럼 추가됨")
                except Exception as e:
                    # 컬럼이 이미 존재하는 경우 무시
                    if "duplicate column name" not in str(e).lower():
                        logger.warning(f"original_text 컬럼 추가 실패: {e}")
                
                # 기존 테이블에 forward_text 컬럼 추가 (마이그레이션)
                try:
                    c.execute("ALTER TABLE messages ADD COLUMN forward_text TEXT NOT NULL DEFAULT ''")
                    logger.info("messages 테이블에 forward_text 컬럼 추가됨")
                except Exception as e:
                    # 컬럼이 이미 존재하는 경우 무시
                    if "duplicate column name" not in str(e).lower():
                        logger.warning(f"forward_text 컬럼 추가 실패: {e}")
                
                # 기존 테이블에 image_paths 컬럼 추가 (마이그레이션)
                try:
                    c.execute("ALTER TABLE messages ADD COLUMN image_paths TEXT NOT NULL DEFAULT '[]'")
                    logger.info("messages 테이블에 image_paths 컬럼 추가됨")
                except Exception as e:
                    # 컬럼이 이미 존재하는 경우 무시
                    if "duplicate column name" not in str(e).lower():
                        logger.warning(f"image_paths 컬럼 추가 실패: {e}")
                
                # 기존 테이블에 forward_info 컬럼 추가 (마이그레이션)
                try:
                    c.execute("ALTER TABLE messages ADD COLUMN forward_info TEXT NOT NULL DEFAULT '{}'")
                    logger.info("messages 테이블에 forward_info 컬럼 추가됨")
                except Exception as e:
                    # 컬럼이 이미 존재하는 경우 무시
                    if "duplicate column name" not in str(e).lower():
                        logger.warning(f"forward_info 컬럼 추가 실패: {e}")
            
            conn.commit()

    def _migrate_schema(self, c, table_exists: bool) -> bool:
        """데이터베이스 스키마 마이그레이션"""
        try:
            # 기존 테이블들의 컬럼 정보 확인
            if table_exists:
                # messages 테이블 컬럼 확인
                c.execute("PRAGMA table_info(messages)")
                messages_columns = c.fetchall()
                messages_column_names = [col[1] for col in messages_columns]
                
                # money_messages 테이블 컬럼 확인
                c.execute("PRAGMA table_info(money_messages)")
                money_columns = c.fetchall()
                money_column_names = [col[1] for col in money_columns]
                
                logger.info(f"현재 messages 테이블 컬럼: {messages_column_names}")
                logger.info(f"현재 money_messages 테이블 컬럼: {money_column_names}")
                
                # 스키마가 일치하지 않으면 테이블 재생성
                expected_messages_columns = [
                    'id', 'chat_id', 'message_id', 'date_ts', 'author', 'text', 
                    'original_text', 'forward_text', 'image_paths', 'forward_info',
                    'embedding', 'importance', 'categories', 'tags', 'summary',
                    'money_making_info', 'action_guide', 'event_products', 'text_hash', 'original_link'
                ]
                
                expected_money_columns = [
                    'id', 'chat_id', 'message_id', 'date_ts', 'author', 'text',
                    'original_text', 'forward_text', 'money_making_info', 'action_guide',
                    'event_products', 'image_paths', 'forward_info', 'embedding', 'text_hash',
                    'original_link', 'importance', 'categories', 'tags', 'summary'
                ]
                
                # 컬럼 순서나 개수가 다르면 테이블 재생성
                if (len(messages_column_names) != len(expected_messages_columns) or
                    messages_column_names != expected_messages_columns or
                    len(money_column_names) != len(expected_money_columns) or
                    money_column_names != expected_money_columns):
                    
                    logger.warning("스키마 불일치 감지. 테이블 재생성 중...")
                    
                    # 기존 데이터 백업
                    if len(messages_column_names) > 0:
                        c.execute("CREATE TABLE messages_backup AS SELECT * FROM messages")
                        logger.info("messages 테이블 백업 완료")
                    
                    if len(money_column_names) > 0:
                        c.execute("CREATE TABLE money_messages_backup AS SELECT * FROM money_messages")
                        logger.info("money_messages 테이블 백업 완료")
                    
                    # 기존 테이블 삭제
                    c.execute("DROP TABLE IF EXISTS messages")
                    c.execute("DROP TABLE IF EXISTS money_messages")
                    logger.info("기존 테이블 삭제 완료")
                    
                    # 테이블 재생성 플래그 설정
                    table_exists = False
                    
        except Exception as e:
            logger.error(f"스키마 마이그레이션 중 오류: {e}")
            # 오류 발생 시 테이블 재생성
            logger.warning("오류로 인해 테이블 재생성을 강제합니다.")
            try:
                c.execute("DROP TABLE IF EXISTS messages")
                c.execute("DROP TABLE IF EXISTS money_messages")
                table_exists = False
            except Exception as drop_error:
                logger.error(f"테이블 삭제 중 오류: {drop_error}")
        
        return table_exists

    def insert_message(
        self,
        chat_id: int,
        message_id: int,
        date_ts: int,
        author: Optional[str],
        text: str,
        original_text: str = "",  # 원본 텍스트
        forward_text: str = "",  # 포워드 텍스트
        image_paths: str = "[]",  # 이미지 경로들 (JSON 형태)
        forward_info: str = "{}",  # 포워드 정보 (JSON 형태)
        embedding_value: str = "[]",  # JSON 형태의 임베딩 벡터
        text_hash: str = "",  # 원본 텍스트의 해시값
        importance: Optional[str] = None,
        categories: Optional[str] = None,
        tags: Optional[str] = None,
        summary: Optional[str] = None,
        original_link: Optional[str] = None,
    ) -> int:
        # 디버깅: 값 타입과 크기 확인
        logger = logging.getLogger("app.storage")
        logger.debug(f"insert_message 호출: chat_id={chat_id} (타입: {type(chat_id)}), message_id={message_id} (타입: {type(message_id)})")
        
        # chat_id와 message_id가 정수인지 확인하고 bit_length 호출
        if isinstance(chat_id, int):
            logger.debug(f"chat_id 크기: {chat_id.bit_length()} bits")
        else:
            logger.warning(f"chat_id가 정수가 아님: {chat_id} (타입: {type(chat_id)})")
            
        if isinstance(message_id, int):
            logger.debug(f"message_id 크기: {message_id.bit_length()} bits")
        else:
            logger.warning(f"message_id가 정수가 아님: {message_id} (타입: {type(message_id)})")
        
        # SQLite INTEGER 범위 확인 (chat_id, message_id만)
        max_sqlite_int = 2**63 - 1
        if isinstance(chat_id, int) and isinstance(message_id, int):
            if chat_id > max_sqlite_int or message_id > max_sqlite_int:
                logger.error(f"SQLite INTEGER 범위 초과: chat_id={chat_id}, message_id={message_id}, 최대값={max_sqlite_int}")
                raise OverflowError(f"SQLite INTEGER 범위 초과: chat_id={chat_id}, message_id={message_id}")
        else:
            logger.error(f"chat_id 또는 message_id가 정수가 아님: chat_id={chat_id} (타입: {type(chat_id)}), message_id={message_id} (타입: {type(message_id)})")
            raise ValueError(f"chat_id와 message_id는 정수여야 함: chat_id={chat_id}, message_id={message_id}")
        
        with self.connect() as conn:
            c = conn.cursor()
            try:
                c.execute(
                    """
                    INSERT OR IGNORE INTO messages (
                        chat_id, message_id, date_ts, author, text, original_text, forward_text, image_paths, forward_info, embedding, text_hash, importance, categories, tags, summary, original_link
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        message_id,
                        date_ts,
                        author,
                        text,
                        original_text,  # 원본 텍스트
                        "",  # forward_text (기본값)
                        "[]",  # image_paths (기본값)
                        "{}",  # forward_info (기본값)
                        embedding_value,  # JSON 형태의 임베딩 벡터
                        text_hash,  # 원본 텍스트의 해시값
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
        event_products: str,
        original_link: str,
    ) -> None:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE messages 
                SET importance = ?, categories = ?, tags = ?, summary = ?, money_making_info = ?, action_guide = ?, event_products = ?, original_link = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (importance, categories, tags, summary, money_making_info, action_guide, event_products, original_link, chat_id, message_id),
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

    def find_exact_duplicate(self, text_hash: str, since_ts: int) -> Optional[Tuple[int, int]]:
        """텍스트 해시를 사용하여 정확한 중복 메시지를 찾습니다."""
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT chat_id, message_id
                FROM messages
                WHERE date_ts >= ? AND text_hash = ?
                ORDER BY date_ts DESC
                LIMIT 1
                """,
                (since_ts, text_hash),
            )
            row = c.fetchone()
            return row if row else None

    def is_message_processed(self, chat_id: int, message_id: int) -> bool:
        """메시지가 이미 처리되었는지 확인합니다."""
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE chat_id = ? AND message_id = ?
                """,
                (chat_id, message_id),
            )
            count = c.fetchone()[0]
            return count > 0

    def mark_message_processed(self, chat_id: int, message_id: int) -> None:
        """메시지를 처리됨으로 표시합니다 (중복 방지용)."""
        try:
            with self.connect() as conn:
                c = conn.cursor()
                # 먼저 메시지가 이미 존재하는지 확인
                c.execute(
                    "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND message_id = ?",
                    (chat_id, message_id)
                )
                count = c.fetchone()[0]
                
                if count == 0:
                    # 메시지가 없으면 새로 삽입
                    c.execute(
                        """
                        INSERT INTO messages (
                            chat_id, message_id, date_ts, author, text, original_text, forward_text, 
                            image_paths, forward_info, embedding, importance, categories, tags, summary,
                            money_making_info, action_guide, event_products, text_hash, original_link
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (chat_id, message_id, 0, None, "", "", "", "[]", "{}", "[]", "low", "", "", "", "", "", "", "", ""),
                    )
                    conn.commit()
                    logger.debug(f"메시지 처리 완료 표시: chat_id={chat_id}, message_id={message_id}")
                else:
                    logger.debug(f"이미 처리된 메시지: chat_id={chat_id}, message_id={message_id}")
        except Exception as e:
            logger.error(f"mark_message_processed 오류: chat_id={chat_id}, message_id={message_id}, 오류={e}")
            # 오류가 발생해도 봇이 계속 동작하도록 예외를 다시 발생시키지 않음

    def get_last_processed_message_id(self, chat_id: int) -> Optional[int]:
        """채널에서 마지막으로 처리된 메시지 ID를 반환합니다."""
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT MAX(message_id)
                FROM messages
                WHERE chat_id = ?
                """,
                (chat_id,),
            )
            result = c.fetchone()[0]
            return result if result else None

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

    def save_money_message(
        self,
        chat_id: int,
        message_id: int,
        date_ts: int,
        author: Optional[str],
        original_text: str,
        forward_text: str,
        money_making_info: str,
        action_guide: str,
        event_products: str,
        image_paths: list,
        forward_info: dict,
        original_link: str,
        importance: str,
        categories: str,
        tags: str,
        summary: str,
    ) -> int:
        """돈버는 정보가 있는 메시지를 별도 테이블에 저장"""
        import json
        
        with self.connect() as conn:
            c = conn.cursor()
            try:
                c.execute(
                    """
                    INSERT OR REPLACE INTO money_messages (
                        chat_id, message_id, date_ts, author, text, original_text, forward_text,
                        money_making_info, action_guide, event_products, image_paths, forward_info,
                        embedding, text_hash, original_link, importance, categories, tags, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        message_id,
                        date_ts,
                        author,
                        original_text,  # text 컬럼에 original_text 사용
                        original_text,
                        forward_text,
                        money_making_info,
                        action_guide,
                        event_products,
                        json.dumps(image_paths),
                        json.dumps(forward_info),
                        "[]",  # embedding (기본값)
                        "",  # text_hash (기본값)
                        original_link,
                        importance,
                        categories,
                        tags,
                        summary,
                    ),
                )
                conn.commit()
                logger.info(f"돈버는 정보 메시지 저장 성공: chat_id={chat_id}, message_id={message_id}")
                return c.lastrowid
            except Exception as e:
                logger.error(f"돈버는 정보 메시지 저장 실패: chat_id={chat_id}, message_id={message_id}, 에러: {e}")
                raise

    def get_money_messages(self, limit: int = 100) -> list[MoneyMessageRecord]:
        """저장된 돈버는 정보 메시지들을 조회"""
        import json
        
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT id, chat_id, message_id, date_ts, author, text, original_text, forward_text,
                       money_making_info, action_guide, event_products, image_paths, forward_info,
                       embedding, text_hash, original_link, importance, categories, tags, summary
                FROM money_messages
                ORDER BY date_ts DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = c.fetchall()
            
            records = []
            for row in rows:
                try:
                    record = MoneyMessageRecord(
                        id=row[0],
                        chat_id=row[1],
                        message_id=row[2],
                        date_ts=row[3],
                        author=row[4],
                        text=row[5],  # text는 5번째 컬럼
                        original_text=row[6],  # original_text는 6번째 컬럼
                        forward_text=row[7],
                        money_making_info=row[8],
                        action_guide=row[9],
                        event_products=row[10],
                        image_paths=row[11],
                        forward_info=row[12],
                        original_link=row[15],  # original_link는 15번째 컬럼
                        importance=row[16],
                        categories=row[17],
                        tags=row[18],
                        summary=row[19],
                    )
                    records.append(record)
                except Exception as e:
                    logger.warning(f"돈버는 정보 메시지 레코드 파싱 실패: {e}")
                    continue
                    
            return records

    def get_recent_message_count(self, seconds: int) -> int:
        """최근 N초 내 메시지 개수를 반환"""
        with self.connect() as conn:
            c = conn.cursor()
            current_ts = int(datetime.utcnow().timestamp())
            since_ts = current_ts - seconds
            c.execute("SELECT COUNT(*) FROM messages WHERE date_ts >= ?", (since_ts,))
            return c.fetchone()[0]

    def get_channel_last_message_id(self, chat_id: int) -> Optional[int]:
        """채널의 마지막으로 처리된 메시지 ID를 반환합니다."""
        try:
            with self.connect() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT last_message_id
                    FROM channel_last_message_ids
                    WHERE chat_id = ?
                    """,
                    (chat_id,),
                )
                result = c.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"get_channel_last_message_id 오류: chat_id={chat_id}, 오류={e}")
            return None

    def update_channel_last_message_id(self, chat_id: int, message_id: int) -> None:
        """채널의 마지막으로 처리된 메시지 ID를 업데이트합니다."""
        try:
            # 방어적 형변환: @username 등 문자열이 들어오는 경우를 숫자 불가로 감지하여 로깅 후 무시
            if not isinstance(chat_id, int):
                try:
                    # -100으로 시작하는 문자열인 경우 정수 변환 시도
                    if isinstance(chat_id, str) and chat_id.startswith("-100"):
                        chat_id = int(chat_id)
                    else:
                        raise TypeError(f"chat_id must be int, got {type(chat_id)}: {chat_id}")
                except Exception as conv_err:
                    logger.error(f"update_channel_last_message_id 형변환 실패: chat_id={chat_id}, 오류={conv_err}")
                    return
            if not isinstance(message_id, int):
                try:
                    message_id = int(message_id)
                except Exception as conv_err:
                    logger.error(f"update_channel_last_message_id 형변환 실패: message_id={message_id}, 오류={conv_err}")
                    return
            with self.connect() as conn:
                c = conn.cursor()
                current_ts = int(datetime.utcnow().timestamp())
                c.execute(
                    """
                    INSERT OR REPLACE INTO channel_last_message_ids (chat_id, last_message_id, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (chat_id, message_id, current_ts),
                )
                conn.commit()
                logger.debug(f"채널 마지막 메시지 ID 업데이트: chat_id={chat_id}, message_id={message_id}")
        except Exception as e:
            logger.error(f"update_channel_last_message_id 오류: chat_id={chat_id}, message_id={message_id}, 오류={e}")
            # 오류가 발생해도 봇이 계속 동작하도록 예외를 다시 발생시키지 않음

    def get_all_channel_last_message_ids(self) -> Dict[int, int]:
        """모든 채널의 마지막 메시지 ID를 반환합니다."""
        try:
            with self.connect() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT chat_id, last_message_id
                    FROM channel_last_message_ids
                    """
                )
                rows = c.fetchall()
                return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(f"get_all_channel_last_message_ids 오류: {e}")
            return {}


