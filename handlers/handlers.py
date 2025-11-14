from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from channel_store import (
    get_menu_buttons,
    get_post,
    remove_link_lines,
    ensure_refreshed,
    get_chain
)

router = Router()

last_view = {}         # user_id → { "base": int, "index": int }
last_message_id = {}   # user_id → message_id


def build_main_keyboard(buttons):
    rows = []
    row = []

    for b in buttons:
        row.append(KeyboardButton(text=b["text"]))

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True
    )


def build_nav_kb(chain, index, base_id):
    nav_buttons = []

    if index > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⏮ Назад",
                callback_data=f"nav:{base_id}:{index - 1}"
            )
        )

    if index < len(chain) - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⏭ Вперёд",
                callback_data=f"nav:{base_id}:{index + 1}"
            )
        )

    rows = []

    # если есть навигация — добавляем её первой строкой
    if nav_buttons:
        rows.append(nav_buttons)

    # кнопка "Заказать" всегда отдельной строкой
    rows.append([
        InlineKeyboardButton(
            text="🛒 Заказать",
            url="https://t.me/MSASeller"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    ensure_refreshed()

    buttons = get_menu_buttons()
    kb = build_main_keyboard(buttons)

    msg = await message.answer("📱 Выберите категорию:", reply_markup=kb)
    last_message_id[message.from_user.id] = msg.message_id


@router.message(F.text)
async def open_category(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    # удаляем сообщение пользователя (чтобы не было мусора в чате)
    try:
        await message.delete()
    except:
        pass

    buttons = get_menu_buttons()
    names = [b["text"] for b in buttons]

    if text not in names:
        return await cmd_start(message)

    button = next(b for b in buttons if b["text"] == text)
    base_id = button["message_id"]

    chain = get_chain(base_id)

    last_view[user_id] = {
        "base": base_id,
        "index": 0
    }

    post_id = chain[0]
    post = get_post(post_id)
    clean = remove_link_lines(post.text)

    kb = build_nav_kb(chain, 0, base_id)

    # 🔧 Пытаемся обновить уже существующее сообщение бота
    target_message_id = last_message_id.get(user_id)

    if target_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=target_message_id,
                text=clean,
                reply_markup=kb
            )
            # на всякий случай фиксируем, хотя ID не меняется
            last_message_id[user_id] = target_message_id
            return
        except Exception:
            # если по какой-то причине редактирование не удалось —
            # падаем в обычную отправку нового сообщения ниже
            pass

    # Если редактировать нечего или произошла ошибка — шлём новое сообщение
    msg = await message.answer(clean, reply_markup=kb)
    last_message_id[user_id] = msg.message_id

@router.callback_query(F.data.startswith("nav:"))
async def nav(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    _, base_id_str, index_str = callback.data.split(":")
    base_id = int(base_id_str)
    index = int(index_str)

    chain = get_chain(base_id)
    post_id = chain[index]

    post = get_post(post_id)
    clean = remove_link_lines(post.text)

    kb = build_nav_kb(chain, index, base_id)

    await callback.message.edit_text(clean, reply_markup=kb)

    last_view[user_id]["index"] = index
