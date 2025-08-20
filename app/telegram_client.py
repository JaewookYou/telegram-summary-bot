from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from telethon import TelegramClient, events, utils
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

        # Use peer_id (-100... for channels/supergroups) to make event filters match
        peer_id = utils.get_peer_id(entity)

        # For private channel links: internal id is abs(peer_id) without leading 100
        internal_id = None
        if isinstance(peer_id, int):
            peer_abs = abs(peer_id)
            s = str(peer_abs)
            if s.startswith("100"):
                internal_id = int(s[3:])

        return ChannelMeta(chat_id=peer_id, title=title, username=username, internal_id=internal_id, is_public=is_public)

    async def send_html(self, target: str | int, html: str) -> Message:
        return await self.client.send_message(target, html, parse_mode="html", link_preview=False)


