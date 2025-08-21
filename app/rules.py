from __future__ import annotations

import re
from typing import List, Tuple


EVENT_TERMS = re.compile(
    r"(이벤트|추첨|경품|기프티콘|커피|스타벅스|나눔|쿠폰|리워드|럭키\s?드로우|라플|raffle|giveaway|bounty|reward|에어\s?드랍|air\s?drop|airdrop)",
    re.IGNORECASE,
)

ACTION_TERMS = re.compile(
    r"(참여|참가|신청|등록|리트윗|\bRT\b|팔로우|팔로윙|팔로|like|좋아요|코멘트|댓글|share|공유|퀘스트|gleam|galxe|zealy)",
    re.IGNORECASE,
)

# 중요 링크 패턴 추가
IMPORTANT_LINK_PATTERNS = [
    # 이벤트/폼 링크
    r"(forms\.google\.com|docs\.google\.com/forms)",
    r"(naver\.com/.*form|naver\.me/.*form)",
    r"(kakao\.com/.*form|kakao\.me/.*form)",
    # 오픈채팅방 맽크
    r"(open\.kakao\.com|kakao\.com/openchat)",
    # 기타 중요 링크
    r"(airdrop|whitelist|presale|ico|ido)",
    r"(event|launch|listing|announcement)",
]

IMPORTANT_LINK_REGEX = re.compile("|".join(IMPORTANT_LINK_PATTERNS), re.IGNORECASE)


def boost_importance_for_events(text: str, current_importance: str) -> Tuple[str, List[str], List[str]]:
    """
    Rule-based boost: If text mentions an event/giveaway and participation/action terms,
    raise importance. Returns (new_importance, extra_categories, extra_tags).
    """
    has_event = EVENT_TERMS.search(text) is not None
    has_action = ACTION_TERMS.search(text) is not None
    has_important_link = IMPORTANT_LINK_REGEX.search(text) is not None

    importance_order = {"low": 0, "medium": 1, "high": 2}
    cur = importance_order.get(current_importance, 0)
    new = cur

    # 중요 링크가 있으면 무조건 high로 부스팅
    if has_important_link:
        new = max(new, importance_order["high"])
    
    # 이벤트 + 액션 키워드가 있으면 high로 부스팅
    elif has_event and has_action:
        new = max(new, importance_order["high"])  # strong boost
    elif has_event:
        new = max(new, importance_order["medium"])  # mild boost

    inv = {v: k for k, v in importance_order.items()}
    new_importance = inv.get(new, current_importance)

    extra_categories: List[str] = []
    extra_tags: List[str] = []
    
    if has_event:
        extra_categories.append("event")
        extra_tags.append("giveaway")
    
    if has_important_link:
        extra_categories.append("important_link")
        extra_tags.append("form_event")

    return new_importance, extra_categories, extra_tags


