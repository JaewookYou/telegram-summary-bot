from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime


def setup_logging():
    """로깅 설정"""
    # 일자별 로그 디렉토리 생성
    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = f"logs/{today}"
    os.makedirs(log_dir, exist_ok=True)
    
    # 기존 logs 디렉토리도 유지 (하위 호환성)
    os.makedirs("logs", exist_ok=True)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 파일 핸들러 (회전) - 일자별 디렉터리
    file_handler = logging.handlers.RotatingFileHandler(
        f"{log_dir}/app.log",
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 에러 전용 파일 핸들러 - 일자별 디렉터리
    error_handler = logging.handlers.RotatingFileHandler(
        f"{log_dir}/error.log",
        maxBytes=20*1024*1024,  # 20MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(pathname)s:%(lineno)d\n',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)

    # 메시지 처리 로거 설정 (더 상세한 로깅)
    msg_logger = logging.getLogger("app.msg")
    msg_logger.setLevel(logging.INFO)
    
    # 메시지 처리 전용 파일 핸들러 - 일자별 디렉터리
    msg_handler = logging.handlers.RotatingFileHandler(
        f"{log_dir}/messages.log",
        maxBytes=100*1024*1024,  # 100MB
        backupCount=20,
        encoding='utf-8'
    )
    msg_handler.setLevel(logging.INFO)
    msg_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    msg_handler.setFormatter(msg_formatter)
    msg_logger.addHandler(msg_handler)
    
    # 전송된 메시지 전용 로거 설정
    sent_logger = logging.getLogger("app.sent")
    sent_logger.setLevel(logging.INFO)
    
    # 전송된 메시지 전용 파일 핸들러 - 일자별 디렉터리
    sent_handler = logging.handlers.RotatingFileHandler(
        f"{log_dir}/sent_messages.log",
        maxBytes=50*1024*1024,  # 50MB
        backupCount=30,
        encoding='utf-8'
    )
    sent_handler.setLevel(logging.INFO)
    sent_formatter = logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    sent_handler.setFormatter(sent_formatter)
    sent_logger.addHandler(sent_handler)
    
    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # 내부 모듈 로그 레벨 조정 (불필요한 로그를 DEBUG로)
    logging.getLogger("app.embedding").setLevel(logging.DEBUG)
    logging.getLogger("app.link").setLevel(logging.DEBUG)
    logging.getLogger("app.image").setLevel(logging.DEBUG)


