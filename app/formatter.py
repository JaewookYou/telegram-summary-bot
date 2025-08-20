from __future__ import annotations

from html import escape
from typing import List, Optional


def build_original_link(chat_id: int, message_id: int, is_public: bool, username: Optional[str], internal_id: Optional[int]) -> str:
    if is_public and username:
        return f"https://t.me/{username}/{message_id}"
    if internal_id is not None:
        # private channel: t.me/c/<internal_id>/<msg_id>
        return f"https://t.me/c/{internal_id}/{message_id}"
    return ""


def format_html(
    source_title: str,
    summary: str,
    importance: str,
    categories: List[str],
    tags: List[str],
    original_link: str,
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
    if link:
        html += f"<a href=\"{link}\">원문 열기</a>"
    return html


