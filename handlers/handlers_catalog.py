# handlers_catalog.py

from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from channel_store import (
	ensure_refreshed,
	get_menu_buttons,
	get_post,
	remove_link_lines
)

router = Router()


# --- /start или любое первое сообщение ---
@router.message(F.text == "/start")
async def cmd_start(message: types.Message):
	ensure_refreshed()

	buttons = get_menu_buttons()
	if not buttons:
		await message.answer("Меню временно недоступно.")
		return

	kb = InlineKeyboardBuilder()
	for btn in buttons:
		kb.button(
			text=btn["text"],
			callback_data=f"post:{btn['message_id']}"
		)

	kb.adjust(2)

	await message.answer(
		"📦 Выберите категорию:",
		reply_markup=kb.as_markup()
	)


# --- обработчик кнопок ---
@router.callback_query(lambda c: c.data.startswith("post:"))
async def show_post(callback: types.CallbackQuery):
	await callback.answer()

	_, id_str = callback.data.split(":", 1)
	msg_id = int(id_str)

	ensure_refreshed()
	post = get_post(msg_id)

	if not post:
		await callback.message.answer("Сообщение не найдено.")
		return

	clean_text = remove_link_lines(post.text)

	# отправляем с медиа или без
	if post.has_media and post.media_file_id:
		await callback.message.answer_photo(
			photo=post.media_file_id,
			caption=clean_text or None
		)
	else:
		await callback.message.answer(clean_text or "Пустое сообщение.")
