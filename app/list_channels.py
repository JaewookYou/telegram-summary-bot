from __future__ import annotations

import argparse
import asyncio
from typing import List

from telethon import TelegramClient, utils
from telethon.tl import functions, types
from telethon.tl.types import Channel, Chat, User

from app.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List joined Telegram channels/groups and build SOURCE_CHANNELS line")
    p.add_argument("--all", action="store_true", help="Include users and normal groups as well (not only channels/supergroups)")
    p.add_argument("--env-line", action="store_true", help="Print a ready-to-paste SOURCE_CHANNELS=... line (channels/supergroups only)")
    p.add_argument("--use-at", action="store_true", help="Use @username format in env line when available (default: plain username)")
    p.add_argument("--include-linked", action="store_true", help="Include linked channels of supergroups/channels (e.g., announcement-channel linked to a community)")
    return p


async def _main(args) -> None:
    settings = load_settings()
    if settings.telegram_api_id == 0 or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH가 필요합니다. .env를 설정하세요.")

    client = TelegramClient(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash)
    await client.start()

    rows: List[dict] = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        title = dialog.name
        username = getattr(entity, "username", None)
        peer_id = utils.get_peer_id(entity)

        entry_type = "unknown"
        include = False

        if isinstance(entity, Channel):
            # Channel can be broadcast or megagroup
            entry_type = "supergroup" if getattr(entity, "megagroup", False) else "channel"
            include = True
        elif isinstance(entity, Chat):
            entry_type = "group"
            include = args.all  # only when --all
        elif isinstance(entity, User):
            entry_type = "user"
            include = args.all  # only when --all

        if not include:
            continue

        rows.append(
            {
                "type": entry_type,
                "title": title or "",
                "username": username,
                "peer_id": peer_id,
                "_entity": entity,
            }
        )

    # Optionally include linked channels for supergroups/channels
    if args.include_linked:
        seen_peer_ids = {r["peer_id"] for r in rows}
        extra_rows: List[dict] = []
        for r in rows:
            if r["type"] not in ("channel", "supergroup"):
                continue
            ent = r.get("_entity")
            if not isinstance(ent, Channel):
                continue
            try:
                full = await client(functions.channels.GetFullChannelRequest(ent))
            except Exception:
                continue
            linked_id = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
            if not linked_id:
                continue
            linked_entity = None
            try:
                linked_entity = await client.get_entity(types.PeerChannel(linked_id))
            except Exception:
                try:
                    linked_entity = await client.get_entity(types.PeerChat(linked_id))
                except Exception:
                    linked_entity = None
            if isinstance(linked_entity, Channel):
                linked_peer = utils.get_peer_id(linked_entity)
                if linked_peer not in seen_peer_ids:
                    extra_rows.append(
                        {
                            "type": "channel",
                            "title": getattr(linked_entity, "title", "") or "",
                            "username": getattr(linked_entity, "username", None),
                            "peer_id": linked_peer,
                            "_entity": linked_entity,
                        }
                    )
                    seen_peer_ids.add(linked_peer)
        rows.extend(extra_rows)

    # Sort for stable output
    rows.sort(key=lambda r: (r["type"], r["title"].lower()))

    # Pretty print
    print("type\tpeer_id\tusername\ttitle")
    for r in rows:
        u = ("@" + r["username"]) if r["username"] else ""
        print(f"{r['type']}\t{r['peer_id']}\t{u}\t{r['title']}")

    if args.env_line:
        # Only channels/supergroups for SOURCE_CHANNELS
        source_items: List[str] = []
        seen_items = set()
        for r in rows:
            if r["type"] in ("channel", "supergroup"):
                if r["username"]:
                    item = ("@" + r["username"]) if args.use_at else r["username"]
                else:
                    # peer_id already includes -100 prefix for channels/supergroups
                    item = str(r["peer_id"])
                if item not in seen_items:
                    source_items.append(item)
                    seen_items.add(item)
        env_line = "SOURCE_CHANNELS=" + ",".join(source_items)
        print("\n" + env_line)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()


