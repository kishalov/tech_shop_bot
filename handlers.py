import re
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from keyboards import main_kb
import time
from handlers_catalog import (
	show_catalog_menu,
	user_cart,
	ensure_catalog_warm,
	CAT_CACHE,
	REFRESH_SECONDS
)


router = Router()
MANAGER_CHAT_ID = -4874196441

def _price_to_int(s: str) -> int:
	digits = re.sub(r"[^\d]", "", s or "")
	return int(digits) if digits else 0

def _build_cart_text(user: types.User, cart: list[dict]) -> str:
	lines = []
	total = 0
	for idx, p in enumerate(cart, start=1):
		name = (p.get("название") or "Без названия").strip()
		desc = (p.get("характеристики") or "").strip()
		price = (p.get("цена") or "").strip()

		line = f"{idx}. <b>{name}</b>"
		if desc:
			line += f" — <i>{desc}</i>"
		if price:
			line += f" — <b>{price}</b>"
			total += _price_to_int(price)
		lines.append(line)

	user_link = f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
	uname = f"@{user.username}" if user.username else "—"
	header = (
		f"🧾 <b>Новый заказ</b>\n"
		f"Дата: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
		f"Клиент: {user_link} ({uname}), id={user.id}\n\n"
	)
	footer = f"\nИтого: <b>{total:,} ₽</b>".replace(",", " ")
	return header + "\n".join(lines) + footer

@router.message(Command("start"))
async def cmd_start(message: types.Message):
	loading_msg = await message.answer("⏳ Загружаем каталог...")
	ensure_catalog_warm()
	try:
		await loading_msg.delete()
	except Exception:
		pass

	await message.answer("👋 Привет!\nИспользуй меню ниже для навигации:", reply_markup=main_kb)

@router.message(Command("refresh"))
async def manual_refresh(message: types.Message):
	ensure_catalog_warm(force=True)
	await message.answer("🔄 Каталог обновлён.")

@router.message(F.text == "📂 Меню")
async def open_catalog(message: types.Message):
	now = time.time()
	# если каталог старее 5 минут — показываем "загрузка"
	if now - CAT_CACHE["built_at"] > REFRESH_SECONDS:
		loading_msg = await message.answer("⏳ Загружаем каталог...")
		ensure_catalog_warm(force=True)
		try:
			await loading_msg.delete()
		except Exception:
			pass
	else:
		ensure_catalog_warm()
	
	await show_catalog_menu(message)

@router.message(F.text == "🛒 Корзина")
async def open_cart(message: types.Message):
	user_id = message.from_user.id
	cart = user_cart.get(user_id, [])
	if not cart:
		await message.answer("🛒 Ваша корзина пуста.")
		return

	text = "🛒 <b>Ваша корзина:</b>\n\n"
	total = 0
	for idx, p in enumerate(cart, start=1):
		name = (p.get("название") or "Без названия").strip()
		desc = (p.get("характеристики") or "").strip()
		price = (p.get("цена") or "").strip()

		line = f"{idx}. <b>{name}</b>"
		if desc:
			line += f" — <i>{desc}</i>"
		if price:
			line += f" — <b>{price}</b>"
			total += _price_to_int(price)
		text += line + "\n"

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

	text = _build_cart_text(callback.from_user, cart)
	await callback.bot.send_message(MANAGER_CHAT_ID, text, parse_mode="HTML", disable_web_page_preview=True)
	await callback.message.answer("✅ Ваш заказ отправлен менеджеру. Мы свяжемся с вами в ближайшее время!")
	user_cart[user_id] = []
