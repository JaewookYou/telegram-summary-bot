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
    money_making_info: str,
    action_guide: str,
    original_link: str,
    image_content: Optional[dict] = None,
    link_content: Optional[dict] = None,
    forward_info: Optional[dict] = None,
    original_snippet: Optional[str] = None,
    extracted_links: Optional[List[str]] = None,
) -> str:
    imp_emoji = {
        "high": "🚨🔥",
        "medium": "⚡",
        "low": "📝",
    }.get(importance, "📝")
    
    # 제목과 본문, 링크는 스타일 적용 전에 이스케이프 처리하여 준비
    title = escape(source_title)
    body = escape(summary)
    link = escape(original_link)

    # 중요도별 스타일 적용
    if importance == "high":
        title_style = f"<b>🚨🔥 {title}</b>"
        body_style = f"<blockquote><b>{body}</b></blockquote>"
    elif importance == "medium":
        title_style = f"<b>⚡ {title}</b>"
        body_style = f"<blockquote>{body}</blockquote>"
    else:
        title_style = f"<b>📝 {title}</b>"
        body_style = f"<blockquote>{body}</blockquote>"

    cats = ", ".join(categories) if categories else "-"
    tag_str = ", ".join(tags) if tags else "-"

    html = (
        f"{title_style}\n"
        f"{body_style}\n"
    )

    # 원문 일부 추가(요청 사항)
    if original_snippet:
        snippet = escape(original_snippet)
        html += f"<b>원문 일부:</b>\n<blockquote>{snippet}</blockquote>\n"

    html += (
        f"<b>Categories:</b> {cats}\n"
        f"<b>Tags:</b> {tag_str}\n"
    )
    
    # 돈 버는 정보와 행동 가이드 추가
    if money_making_info and money_making_info != "없음":
        money_info = escape(money_making_info)
        action = escape(action_guide)
        html += f"<b>💰 돈 버는 정보:</b> {money_info}\n"
        html += f"<b>🎯 행동 가이드:</b> {action}\n"
    
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
    
    # 추출된 링크 목록 추가
    if extracted_links:
        html += f"<b>🔗 포함된 링크:</b>\n"
        for i, link in enumerate(extracted_links, 1):
            html += f"{i}. {escape(link)}\n"
    
    # 포워드 정보 추가
    if forward_info:
        forward_channel = escape(forward_info.get("forward_channel", "Unknown"))
        original_channel = escape(forward_info.get("original_channel", "Unknown"))
        html += f"<b>📤 포워드:</b> {forward_channel} → {original_channel}\n"
    
    if link:
        html += f"<a href=\"{link}\">원문 열기</a>"
    return html


