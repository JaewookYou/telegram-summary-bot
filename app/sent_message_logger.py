from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from datetime import datetime


class SentMessageLogger:
    def __init__(self):
        self.logger = logging.getLogger("app.sent")
    
    def log_sent_message(
        self,
        source_channel: str,
        source_username: str,
        message_id: int,
        importance: str,
        categories: list,
        tags: list,
        summary: str,
        money_making_info: str,
        action_guide: str,
        original_link: str,
        has_image: bool = False,
        has_link: bool = False,
        is_forward: bool = False,
        forward_info: Optional[Dict[str, Any]] = None,
    ):
        """전송된 메시지를 로깅합니다."""
        
        # 기본 정보
        log_parts = [
            f"SOURCE: {source_channel} (@{source_username})",
            f"MSG_ID: {message_id}",
            f"IMPORTANCE: {importance.upper()}",
        ]
        
        # 카테고리와 태그
        if categories:
            log_parts.append(f"CATEGORIES: {', '.join(categories)}")
        if tags:
            log_parts.append(f"TAGS: {', '.join(tags)}")
        
        # 요약
        if summary:
            log_parts.append(f"SUMMARY: {summary}")
        
        # 돈 버는 정보
        if money_making_info and money_making_info != "없음":
            log_parts.append(f"MONEY_INFO: {money_making_info}")
        
        # 행동 가이드
        if action_guide and action_guide != "추가 정보 대기":
            log_parts.append(f"ACTION: {action_guide}")
        
        # 미디어 정보
        media_info = []
        if has_image:
            media_info.append("IMAGE")
        if has_link:
            media_info.append("LINK")
        if is_forward:
            media_info.append("FORWARD")
        
        if media_info:
            log_parts.append(f"MEDIA: {', '.join(media_info)}")
        
        # 포워드 정보
        if forward_info:
            forward_channel = forward_info.get("forward_channel", "Unknown")
            original_channel = forward_info.get("original_channel", "Unknown")
            log_parts.append(f"FORWARD_FROM: {forward_channel} → {original_channel}")
        
        # 원문 링크
        log_parts.append(f"LINK: {original_link}")
        
        # 로그 메시지 생성
        log_message = " | ".join(log_parts)
        self.logger.info(log_message)
    
    def log_sent_message_simple(
        self,
        source_channel: str,
        message_id: int,
        importance: str,
        summary: str,
        money_making_info: str = "",
        action_guide: str = "",
    ):
        """간단한 형태로 전송된 메시지를 로깅합니다."""
        
        log_parts = [
            f"CHANNEL: {source_channel}",
            f"MSG_ID: {message_id}",
            f"IMPORTANCE: {importance.upper()}",
            f"SUMMARY: {summary}",
        ]
        
        if money_making_info and money_making_info != "없음":
            log_parts.append(f"MONEY: {money_making_info}")
        
        if action_guide and action_guide != "추가 정보 대기":
            log_parts.append(f"ACTION: {action_guide}")
        
        log_message = " | ".join(log_parts)
        self.logger.info(log_message)
