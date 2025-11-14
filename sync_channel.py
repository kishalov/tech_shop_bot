import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from dataclasses import dataclass
from typing import Optional, List, Dict

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
source_channel = os.getenv("SOURCE_CHANNEL")

client = TelegramClient("sync_session", api_id, api_hash)

# ---------------------------
#   Модель поста
# ---------------------------
@dataclass
class ChannelPost:
    id: int
    text: str
    has_media: bool = False
    media_file_id: Optional[str] = None


URL_RE = re.compile(r"/(\d+)$")


def extract_id(url: str) -> Optional[int]:
    m = URL_RE.search(url)
    return int(m.group(1)) if m else None


# ===================================================
#   Чтение кнопок из меню-сообщения
# ===================================================
async def fetch_menu_buttons(menu_message_id: int) -> list[dict]:
    msg = await client.get_messages(source_channel, ids=menu_message_id)
    if not msg or not msg.reply_markup:
        return []

    buttons = []

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if not getattr(btn, "url", None):
                continue

            mid = extract_id(btn.url)
            if not mid:
                continue

            buttons.append({
                "text": btn.text,
                "message_id": mid
            })

    return buttons


# ===================================================
#   Загрузка одного сообщения
# ===================================================
async def fetch_post(mid: int) -> Optional[ChannelPost]:
    msg = await client.get_messages(source_channel, ids=mid)
    if not msg:
        return None

    text = msg.message or ""
    has_media = False
    media = None

    if isinstance(msg.media, MessageMediaPhoto):
        has_media = True
        media = msg.photo

    elif isinstance(msg.media, MessageMediaDocument):
        has_media = True
        media = msg.document

    return ChannelPost(
        id=mid,
        text=text,
        has_media=has_media,
        media_file_id=media
    )


# ===================================================
#   Построение цепочек “продолжение“
# ===================================================
async def build_chains(base_ids: list[int]) -> (list[ChannelPost], dict):
    """
    Строим цепочки не по ID, а по времени создания сообщения.
    """
    # Загружаем ВСЕ сообщения канала за последние N (например, 3000)
    all_msgs = []
    async for msg in client.iter_messages(source_channel, limit=3000):
        if msg.message:
            all_msgs.append(msg)

    # Сортировка по дате (самое старое → самое новое)
    all_msgs.sort(key=lambda m: m.date)

    # Словарь для быстрого поиска: (id → объект)
    post_map: dict[int, ChannelPost] = {}

    for m in all_msgs:
        media = None
        has_media = False

        if isinstance(m.media, MessageMediaPhoto):
            has_media = True
            media = m.photo
        elif isinstance(m.media, MessageMediaDocument):
            has_media = True
            media = m.document

        post_map[m.id] = ChannelPost(
            id=m.id,
            text=m.message or "",
            has_media=has_media,
            media_file_id=media
        )

    # Теперь строим цепочки
    chains: dict[int, list[int]] = {}

    # Подготовим список только ID (в порядке времени)
    ordered_ids = [m.id for m in all_msgs]

    for base in base_ids:
        if base not in post_map:
            continue

        chain = [base]
        current = base

        while True:
            # текущий пост
            cur_post = post_map[current]
            text = (cur_post.text or "").lower()

            # если нет "продолжение" — конец
            if "продолжение" not in text:
                break

            # находим индекс в хронологии
            idx = ordered_ids.index(current)

            # если этот пост был последним — выхода нет
            if idx == len(ordered_ids) - 1:
                break

            # следующий по времени
            nxt = ordered_ids[idx + 1]
            chain.append(nxt)
            current = nxt

        chains[base] = chain

    # возвращаем все посты и цепочки
    return list(post_map.values()), chains

# ===================================================
#   Главная функция синхронизации
# ===================================================
async def sync_channel(menu_message_id: int):
    print("🔍 Синхронизирую канал…")

    buttons = await fetch_menu_buttons(menu_message_id)

    if not buttons:
        print("⚠ Не удалось получить кнопки.")
        return [], []

    base_ids = [b["message_id"] for b in buttons]
    base_ids = list(set(base_ids))

    # загружаем все цепочки
    posts, chains = await build_chains(base_ids)

    print("🔎 Полностью загружены посты:", list(chains.keys()))
    print(f"📨 Получено сообщений: {len(posts)}")

    return posts, buttons, chains
