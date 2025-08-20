from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from telethon import TelegramClient, events
from telethon.tl.types import Message


@dataclass
class ChannelMeta:
    chat_id: int
    title: str
    username: Optional[str]
    internal_id: Optional[int]
    is_public: bool


class TG:
    def __init__(self, session: str, api_id: int, api_hash: str) -> None:
        self.client = TelegramClient(session, api_id, api_hash)

    async def start(self):
        await self.client.start()
        return self

    def on_new_message(self, handler, chats: Optional[list] = None):
        self.client.add_event_handler(handler, events.NewMessage(chats=chats))

    async def iter_channel_meta(self, identifier: str) -> Optional[ChannelMeta]:
        entity = await self.client.get_entity(identifier)
        title = getattr(entity, "title", getattr(entity, "first_name", str(identifier)))
        username = getattr(entity, "username", None)
        is_public = username is not None
        chat_id = getattr(entity, "id", 0)
        internal_id = None
        # For private channel links: internal id is abs(chat_id) stripped of -100 prefix
        if isinstance(chat_id, int) and chat_id < 0:
            # channel ids often like -1001234567890 → internal 1234567890
            internal_id = abs(chat_id) if str(abs(chat_id)).startswith("100") else None
            if internal_id and str(internal_id).startswith("100"):
                internal_id = int(str(internal_id)[3:])
        return ChannelMeta(chat_id=chat_id, title=title, username=username, internal_id=internal_id, is_public=is_public)

    async def send_html(self, target: str | int, html: str) -> Message:
        return await self.client.send_message(target, html, parse_mode="html", link_preview=False)


