import os
import time
import asyncio
import re
from dataclasses import dataclass
from typing import Optional, List, Dict

from sync_channel import sync_channel, ChannelPost

REFRESH_SECONDS = 600

APPLE_KEYWORDS = [
    "Apple", "iPhone", "iPad", "Mac", "AirPods", "Watch", "iMac"
]

@dataclass
class ChannelPost:
    id: int
    text: str
    has_media: bool = False
    media_file_id: Optional[str] = None


_STORE: Dict[int, ChannelPost] = {}
_MENU_BUTTONS: List[dict] = []
_CHAINS: Dict[int, List[int]] = {}   # добавлено
_LAST_REFRESH = 0.0

_LINK_RE = re.compile(r'https?://\S+')


def remove_link_lines(text: str) -> str:
    if not text:
        return ""

    lines = text.split("\n")
    cleaned = []

    for line in lines:
        if _LINK_RE.search(line):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def get_menu_buttons() -> List[dict]:
    return [
        b for b in _MENU_BUTTONS
        if any(k.lower() in b["text"].lower() for k in APPLE_KEYWORDS)
    ]


def get_post(message_id: int) -> Optional[ChannelPost]:
    return _STORE.get(message_id)


def get_chain(base_id: int) -> List[int]:
    return _CHAINS.get(base_id, [base_id])


async def _do_refresh() -> None:
    global _STORE, _MENU_BUTTONS, _CHAINS, _LAST_REFRESH

    print("🔄 Запуск обновления данных канала…")

    menu_id = os.getenv("MENU_MESSAGE_ID")
    if not menu_id:
        raise RuntimeError("❌ MENU_MESSAGE_ID не указан")
    menu_id = int(menu_id)

    posts, buttons, chains = await sync_channel(menu_id)

    _MENU_BUTTONS = buttons
    _CHAIN = chains

    _STORE.clear()
    for p in posts:
        _STORE[p.id] = p

    _CHAINS = chains
    _LAST_REFRESH = time.time()

    print(f"📦 Обновление завершено: {len(posts)} постов, {len(buttons)} кнопок.")


def ensure_refreshed(force: bool = False) -> None:
    now = time.time()

    need = (
        force or
        not _MENU_BUTTONS or
        not _STORE or
        (now - _LAST_REFRESH) > REFRESH_SECONDS
    )

    if not need:
        return

    loop = asyncio.get_event_loop()
    loop.create_task(_do_refresh())
