from __future__ import annotations

from html import escape
from typing import List, Optional
import logging


def build_original_link(chat_id: int, message_id: int, is_public: bool, username: Optional[str], internal_id: Optional[int]) -> str:
    logger = logging.getLogger("app.formatter")
    
    logger.info(f"링크 생성: chat_id={chat_id}, msg_id={message_id}, is_public={is_public}, username={username}, internal_id={internal_id}")
    
    if is_public and username:
        link = f"https://t.me/{username}/{message_id}"
        logger.info(f"공개 채널 링크 생성: {link}")
        return link
    
    if internal_id is not None:
        # private channel: t.me/c/<internal_id>/<msg_id>
        link = f"https://t.me/c/{internal_id}/{message_id}"
        logger.info(f"비공개 채널 링크 생성: {link}")
        return link
    
    # 링크를 생성할 수 없는 경우
    logger.warning(f"링크 생성 실패: chat_id={chat_id}, msg_id={message_id}, is_public={is_public}, username={username}, internal_id={internal_id}")
    return ""


def format_html(
    source_title: str,
    summary: str,
    importance: str,
    categories: List[str],
    tags: List[str],
    original_link: str,
    image_content: Optional[dict] = None,
    link_content: Optional[dict] = None,
) -> str:
    imp_emoji = {
        "high": "🔥",
        "medium": "⚡",
        "low": "📝",
    }.get(importance, "📝")

    cats = ", ".join(categories) if categories else "-"
    tag_str = ", ".join(tags) if tags else "-"
    title = escape(source_title)
    body = escape(summary)
    link = escape(original_link)

    html = (
        f"<b>{imp_emoji} {title}</b>\n"
        f"<blockquote>{body}</blockquote>\n"
        f"<b>Categories:</b> {cats}\n"
        f"<b>Tags:</b> {tag_str}\n"
    )
    
    # 이미지 정보 추가
    if image_content:
        img_desc = escape(image_content.get("description", ""))
        html += f"<b>📷 이미지:</b> {img_desc}\n"
    
    # 링크 정보 추가
    if link_content:
        link_title = escape(link_content.get("title", "")[:100])
        link_domain = escape(link_content.get("domain", ""))
        html += f"<b>🔗 링크:</b> {link_title}\n"
        html += f"<b>🌐 도메인:</b> {link_domain}\n"
    
    if link:
        html += f"<a href=\"{link}\">원문 열기</a>"
    return html


