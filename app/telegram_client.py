from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from telethon import TelegramClient, events, utils, functions
from telethon.tl.types import Message, Channel, Chat, User
import aiohttp
import json


@dataclass
class ChannelMeta:
    chat_id: int
    title: str
    username: Optional[str]
    internal_id: Optional[int]
    is_public: bool
    chat_type: str  # "channel", "group", "supergroup"
    is_forum: bool  # 토픽 기능 활성화 여부
    linked_chat_id: Optional[int]  # 연결된 채널/그룹 ID
    has_chat: bool  # 채팅 기능 활성화 여부 (사람들이 대화할 수 있는지)
    is_megagroup: bool  # 하위 호환성
    is_broadcast: bool  # 하위 호환성


class TG:
    def __init__(self, session: str, api_id: int, api_hash: str, bot_token: str = None) -> None:
        self.client = TelegramClient(session, api_id, api_hash)
        self.bot_token = bot_token

    async def start(self):
        await self.client.start()
        return self

    def on_new_message(self, handler, chats: Optional[list] = None):
        self.client.add_event_handler(handler, events.NewMessage(chats=chats))

    async def iter_channel_meta(self, identifier: str) -> Optional[ChannelMeta]:
        try:
            entity = await self.client.get_entity(identifier)
        except ValueError as e:
            # 채널을 찾을 수 없는 경우 예외를 다시 발생시켜 상위에서 처리하도록 함
            raise e
        except Exception as e:
            # 기타 예외도 상위로 전파
            raise e
        title = getattr(entity, "title", getattr(entity, "first_name", str(identifier)))
        username = getattr(entity, "username", None)
        is_public = username is not None

        # Use peer_id (-100... for channels/supergroups) to make event filters match
        # entity가 유효한 Peer 객체인지 확인 (Channel, User, Chat 등 허용)
        if (hasattr(entity, 'id') and 
            not isinstance(entity, str) and 
            hasattr(entity, '__class__')):
            peer_id = utils.get_peer_id(entity)
        else:
            raise ValueError(f"유효하지 않은 엔티티 타입: {type(entity)}")

        # Bot API를 통해 정확한 권한 정보 가져오기
        bot_permissions = {}
        if self.bot_token and username:
            bot_permissions = await self.get_chat_permissions(f"@{username}")
        
        # Bot API 정보가 있으면 우선 사용, 없으면 Telethon 정보 사용
        if bot_permissions:
            chat_type = bot_permissions.get("chat_type", "unknown")
            linked_chat_id = bot_permissions.get("linked_chat_id")
            
            # Bot API 기반 채팅 가능 여부 판단
            can_send_messages = bot_permissions.get("can_send_messages", False)
            join_to_send_messages = bot_permissions.get("join_to_send_messages", False)
            
            # 채팅 기능이 있는지 판단: 메시지 전송 가능하거나 가입 후 전송 가능
            has_chat = can_send_messages or join_to_send_messages
            
            # 슈퍼그룹의 경우 토픽 기능 확인
            is_forum = False
            if chat_type == "supergroup":
                try:
                    if isinstance(entity, Channel):
                        is_forum = getattr(entity, "forum", False)
                except:
                    pass
        else:
            # Bot API 정보가 없는 경우 Telethon 정보 사용 (fallback)
            chat_type = "unknown"
            is_forum = False
            linked_chat_id = None
            has_chat = False
            
            if isinstance(entity, Channel):
                if getattr(entity, "broadcast", False):
                    chat_type = "channel"
                    has_chat = False
                elif getattr(entity, "megagroup", False):
                    chat_type = "supergroup"
                    is_forum = getattr(entity, "forum", False)
                    has_chat = True
                else:
                    chat_type = "channel"
                    has_chat = False
            elif isinstance(entity, Chat):
                chat_type = "group"
                has_chat = True
            elif isinstance(entity, User):
                chat_type = "user"
                has_chat = True
            
            # 연결된 채널/그룹 ID 확인 (linked_chat_id)
            try:
                if isinstance(entity, Channel):
                    full_channel = await self.client(functions.channels.GetFullChannelRequest(entity))
                    linked_chat_id = getattr(getattr(full_channel, "full_chat", None), "linked_chat_id", None)
            except Exception:
                pass

        # 하위 호환성을 위한 기존 플래그들
        is_megagroup = chat_type == "supergroup"
        is_broadcast = chat_type == "channel"

        # For private channel links: internal id is abs(peer_id) without leading 100
        internal_id = None
        if isinstance(peer_id, int):
            peer_abs = abs(peer_id)
            s = str(peer_abs)
            if s.startswith("100"):
                internal_id = int(s[3:])

        return ChannelMeta(
            chat_id=peer_id,
            title=title,
            username=username,
            internal_id=internal_id,
            is_public=is_public,
            chat_type=chat_type,
            is_forum=is_forum,
            linked_chat_id=linked_chat_id,
            has_chat=has_chat,
            is_megagroup=is_megagroup,
            is_broadcast=is_broadcast,
        )

    async def send_html(self, target: str | int, html: str) -> Message:
        return await self.client.send_message(target, html, parse_mode="html", link_preview=True)

    async def get_chat_permissions(self, chat_id: str) -> dict:
        """Bot API를 통해 채팅 권한 정보를 가져옵니다."""
        if not self.bot_token:
            return {}
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getChat"
            params = {"chat_id": chat_id}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("ok"):
                            result = data.get("result", {})
                            permissions = result.get("permissions", {})
                            
                            return {
                                "can_send_messages": permissions.get("can_send_messages", False),
                                "join_to_send_messages": result.get("join_to_send_messages", False),
                                "chat_type": result.get("type", "unknown"),
                                "title": result.get("title", ""),
                                "username": result.get("username", ""),
                                "linked_chat_id": result.get("linked_chat_id"),
                                "description": result.get("description", "")
                            }
            return {}
        except Exception as e:
            print(f"Bot API 호출 실패: {e}")
            return {}


