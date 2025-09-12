from aiogram import Router, types, F
from aiogram.filters import Command
from keyboards import main_kb
from handlers_catalog import show_catalog_menu, user_cart, ensure_catalog_warm
import re
from datetime import datetime

router = Router()

# 👉 сюда подставь id менеджера или группы
MANAGER_CHAT_ID = -4874196441

def _price_to_int(s: str) -> int:
    """'12 300 ₽' -> 12300; '9,200₽' -> 9200"""
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else 0

def _build_cart_text(user: types.User, cart: list[dict]) -> str:
    lines = []
    total = 0
    for idx, p in enumerate(cart, start=1):
        parts = [p.get("название", "Без названия")]
        if p.get("цвет"):
            parts.append(p["цвет"])
        if p.get("характеристики"):
            parts.append(p["характеристики"])
        if p.get("цена"):
            parts.append(str(p["цена"]))
            total += _price_to_int(str(p["цена"]))
        lines.append(f"{idx}. " + " — ".join(parts))

    user_link = f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
    uname = f"@{user.username}" if user.username else "—"

    header = (
        f"🧾 <b>Новый заказ</b>\n"
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Клиент: {user_link} ({uname}), id={user.id}\n\n"
    )
    footer = f"\nИтого: <b>{total:,} ₽</b>".replace(",", " ")
    return header + "\n".join(lines) + footer


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    # показываем заглушку
    loading_msg = await message.answer("⏳ Загружаем каталог...")

    # прогреваем кэш
    ensure_catalog_warm()

    # удаляем заглушку
    try:
        await loading_msg.delete()
    except Exception:
        pass  # если вдруг не получилось удалить — ничего страшного

    # отправляем основное приветствие
    await message.answer(
        "👋 Привет!\nИспользуй меню ниже для навигации:",
        reply_markup=main_kb
    )


@router.message(Command("refresh"))
async def manual_refresh(message: types.Message):
    ensure_catalog_warm(force=True)
    await message.answer("🔄 Каталог обновлён.") 


@router.message(F.text == "📂 Меню")
async def open_catalog(message: types.Message):
    await show_catalog_menu(message)


@router.message(F.text == "🛒 Корзина")
async def open_cart(message: types.Message):
    user_id = message.from_user.id
    cart = user_cart.get(user_id, [])

    if not cart:
        await message.answer("🛒 Ваша корзина пока пуста.")
        return

    text = "🛒 Ваша корзина:\n\n"
    total = 0
    for idx, p in enumerate(cart, start=1):
        parts = [p.get("название", "Без названия")]
        if p.get("цвет"):
            parts.append(p["цвет"])
        if p.get("характеристики"):
            parts.append(p["характеристики"])
        if p.get("цена"):
            price = str(p["цена"])
            parts.append(price)
            # вычленяем цифры для подсчёта суммы
            digits = re.sub(r"[^\d]", "", price)
            if digits:
                total += int(digits)
        text += f"{idx}. " + " — ".join(parts) + "\n"

    # добавляем пустую строку и итог
    text += f"\nИтого: <b>{total:,} ₽</b>".replace(",", " ")

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="✅ Заказать", callback_data="checkout")]]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "checkout")
async def checkout(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    cart = user_cart.get(user_id, [])

    if not cart:
        await callback.message.answer("🛒 Ваша корзина пуста.")
        return

    # отправляем заказ менеджеру
    text = _build_cart_text(callback.from_user, cart)
    await callback.bot.send_message(MANAGER_CHAT_ID, text, parse_mode="HTML", disable_web_page_preview=True)

    # подтверждаем пользователю
    await callback.message.answer("✅ Ваш заказ отправлен менеджеру. Мы свяжемся с вами в ближайшее время!")

    # очищаем корзину
    user_cart[user_id] = []
