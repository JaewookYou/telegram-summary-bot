#!/usr/bin/env python3
"""
SQLite 마이그레이션 스크립트
기존 INTEGER 컬럼을 BIGINT로 변경
"""

import sqlite3
import os
import sys
from pathlib import Path

def migrate_database(db_path: str) -> None:
    """기존 데이터베이스를 BIGINT 스키마로 마이그레이션"""
    
    if not os.path.exists(db_path):
        print(f"데이터베이스 파일이 존재하지 않습니다: {db_path}")
        return
    
    # 백업 생성
    backup_path = f"{db_path}.backup"
    if not os.path.exists(backup_path):
        print(f"백업 생성 중: {backup_path}")
        with open(db_path, 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 현재 스키마 확인
        cursor.execute("PRAGMA table_info(messages)")
        columns = cursor.fetchall()
        
        # message_id와 chat_id 컬럼 타입 확인
        message_id_col = next((col for col in columns if col[1] == 'message_id'), None)
        chat_id_col = next((col for col in columns if col[1] == 'chat_id'), None)
        
        if message_id_col and message_id_col[2] == 'INTEGER':
            print("message_id 컬럼을 BIGINT로 변경 중...")
            # 임시 테이블 생성
            cursor.execute("""
                CREATE TABLE messages_new (
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
            """)
            
            # 데이터 복사
            cursor.execute("""
                INSERT INTO messages_new 
                SELECT * FROM messages
            """)
            
            # 기존 테이블 삭제 및 새 테이블 이름 변경
            cursor.execute("DROP TABLE messages")
            cursor.execute("ALTER TABLE messages_new RENAME TO messages")
            
            # 인덱스 재생성
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_date_ts ON messages(date_ts)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_simhash ON messages(simhash)")
            
            conn.commit()
            print("마이그레이션 완료!")
        else:
            print("마이그레이션이 필요하지 않습니다 (이미 BIGINT 사용 중)")
            
    except Exception as e:
        print(f"마이그레이션 실패: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    # 환경변수에서 DB 경로 가져오기
    db_path = os.getenv("SQLITE_PATH", "data/db.sqlite3")
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    print(f"데이터베이스 마이그레이션 시작: {db_path}")
    migrate_database(db_path)
