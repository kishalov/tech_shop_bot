# handlers_catalog.py
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pathlib import Path
from aiogram.types import BufferedInputFile, InputMediaPhoto
from sheets import get_products
from collections import defaultdict
import aiohttp

NO_PHOTO_PATH = Path(__file__).parent / "static" / "no-photo.jpg"

router = Router()

# Память: текущая страница по пользователю и корзина
user_pages: dict[int, dict] = {}
user_cart: dict[int, list] = {}

def group_by_category(products):
    grouped = defaultdict(list)
    for p in products:
        grouped[p.get("категория") or "Без категории"].append(p)
    return grouped

# ---------- helpers ----------
async def _download_image(url: str, timeout: int = 15) -> BufferedInputFile | None:
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout, allow_redirects=True) as r:
                if r.status != 200:
                    return None
                # иногда Drive отдаёт html — отфильтруем по типу
                ctype = (r.headers.get("Content-Type") or "").lower()
                data = await r.read()
                head = data[:256].lower()
                if ("image" not in ctype) and (b"<html" in head or b"<!doctype html" in head):
                    return None
        return BufferedInputFile(data, filename="photo.jpg")
    except Exception:
        return None
# --------------------------------

@router.message(Command("catalog"))
async def show_categories(message: types.Message):
    products = get_products()
    grouped = group_by_category(products)

    kb = InlineKeyboardBuilder()
    for cat in grouped.keys():
        kb.button(text=cat, callback_data=f"cat:{cat}")
    kb.adjust(2)

    await message.answer("📂 Выберите категорию:", reply_markup=kb.as_markup())

@router.callback_query(lambda c: c.data.startswith("cat:"))
async def show_products(callback: types.CallbackQuery):
    await callback.answer()  # погасить крутилку
    cat = callback.data.split(":", 1)[1]

    products = get_products()
    grouped = group_by_category(products)
    items = grouped.get(cat, [])

    page = 0
    user_pages[callback.from_user.id] = {"category": cat, "page": page}
    await send_product_card(callback.message, items, cat, page)

def _build_card_text(p: dict) -> str:
    return (
        f"<b>{p.get('название','')}</b>\n\n"
        f"📏 Кол-во: {p.get('кол-во','')}\n"
        f"💪 Сила: {p.get('сила','')}\n"
        f"📝 {p.get('описание','')}\n"
        f"🏭 {p.get('бренд','')}\n"
        f"📂 {p.get('категория','')}\n\n"
        f"💵 <b>{p.get('цена','')}</b>\n"
    )

def _build_nav(cat: str, page: int, total: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ В корзину", callback_data=f"add:{cat}:{page}")
    if page > 0:
        kb.button(text="⬅ Назад", callback_data=f"page:{cat}:{page-1}")
    if page < total - 1:
        kb.button(text="➡ Вперёд", callback_data=f"page:{cat}:{page+1}")
    return kb.as_markup()

async def send_product_card(msg: types.Message, items: list[dict], cat: str, page: int):
    if not items:
        try:
            await msg.edit_text("❌ В этой категории нет товаров.")
        except Exception:
            await msg.answer("❌ В этой категории нет товаров.")
        return

    p = items[page]
    text = _build_card_text(p)
    markup = _build_nav(cat, page, len(items))

    photo_url: str = p.get("фото") or ""

    if photo_url:
        f = await _download_image(photo_url)
    else:
        # берём локальную заглушку
        f = BufferedInputFile(open(NO_PHOTO_PATH, "rb").read(), filename="no_photo.png")

    if not f:
        # если ничего не получилось — хотя бы текст покажем
        try:
            await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await msg.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    # пробуем заменить медиа
    try:
        await msg.edit_media(
            media=InputMediaPhoto(media=f, caption=text, parse_mode="HTML"),
            reply_markup=markup
        )
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        await msg.answer_photo(f, caption=text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("page:"))
async def paginate(callback: types.CallbackQuery):
    await callback.answer()  # погасить крутилку
    _, cat, page = callback.data.split(":")
    page = int(page)

    products = get_products()
    grouped = group_by_category(products)
    items = grouped.get(cat, [])

    user_pages[callback.from_user.id] = {"category": cat, "page": page}
    await send_product_card(callback.message, items, cat, page)

@router.callback_query(lambda c: c.data.startswith("add:"))
async def add_to_cart(callback: types.CallbackQuery):
    _, cat, page = callback.data.split(":")
    page = int(page)

    products = get_products()
    grouped = group_by_category(products)
    items = grouped.get(cat, [])
    if not items:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return

    product = items[page]
    user_id = callback.from_user.id
    user_cart.setdefault(user_id, []).append(product)

    # показываем тост
    await callback.answer(f"✅ {product.get('название','Товар')} добавлен в корзину!", show_alert=False)
