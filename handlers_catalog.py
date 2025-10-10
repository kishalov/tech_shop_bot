import re
import time
from collections import defaultdict
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sheets import get_products

router = Router()

REFRESH_SECONDS = 600
CAT_CACHE = {"built_at": 0, "by_category": {}}
MAX_TG_LEN = 4000

user_cart: dict[int, list[dict]] = {}
subcat_context: dict[int, list[dict]] = {}
pending_add: dict[int, dict] = {}

# --- группировка ---
def group_by_category(products: list[dict]) -> dict[str, list[dict]]:
	grouped = defaultdict(list)
	for p in products:
		grouped[p.get("категория") or "Прочее"].append(p)
	return grouped

# --- форматирование ---
def _format_item_one_line(p: dict) -> str:
	name = (p.get("название") or "").strip()
	desc = (p.get("характеристики") or "").strip()
	price = (p.get("цена") or "").strip()

	parts = []

	# 🔹 Название — жирным
	if name:
		parts.append(f"<b>{name}</b>")

	# 🔹 Характеристики — курсивом (если есть)
	if desc:
		parts.append(f"<i>{desc}</i>")

	# 🔹 Цена — жирным + эмодзи 💰
	if price:
		parts.append(f"💰 <b>{price}</b>")

	# Каждая строка как аккуратная карточка товара
	return " — ".join(parts)

# --- сборка вида ---
def _build_catalog_views(products: list[dict]) -> dict[str, list[dict]]:
	by_cat = {}
	cats = group_by_category(products)
	for cat, items in cats.items():
		lines = [f"{i}) {_format_item_one_line(p)}" for i, p in enumerate(items, start=1)]
		text = "\n".join(lines)
		if len(text) > MAX_TG_LEN:
			text = text[:MAX_TG_LEN - 1] + "…"
		by_cat[cat] = [{"text": text, "plist": items}]
	return by_cat

# --- обновление кэша ---
def ensure_catalog_warm(force: bool = False):
	now = time.time()
	if (not force) and CAT_CACHE["by_category"] and (now - CAT_CACHE["built_at"] < REFRESH_SECONDS):
		return
	products = get_products()
	CAT_CACHE["by_category"] = _build_catalog_views(products)
	CAT_CACHE["built_at"] = now

# --- меню категорий ---
async def show_catalog_menu(message: types.Message):
	ensure_catalog_warm()
	cats = list(CAT_CACHE["by_category"].keys())

	# 🔹 перемещаем "Прочее" в конец
	cats_sorted = sorted(
		[c for c in cats if c.lower() != "прочее"],
		key=lambda x: x.lower()
	)
	if "Прочее" in cats:
		cats_sorted.append("Прочее")

	kb = InlineKeyboardBuilder()
	for cat in cats_sorted:
		kb.button(text=cat, callback_data=f"cat:{cat}")
	kb.adjust(2)

	await message.answer("📂 Выберите категорию:", reply_markup=kb.as_markup())

# --- товары категории ---
@router.callback_query(lambda c: c.data.startswith("cat:"))
async def show_products(callback: types.CallbackQuery):
	await callback.answer()
	_, value = callback.data.split(":", 1)
	ensure_catalog_warm()
	views = CAT_CACHE["by_category"].get(value, [])

	try:
		await callback.message.edit_text(f"📦 Категория: {value}")
	except Exception:
		await callback.message.answer(f"📦 Категория: {value}")

	kb_one = InlineKeyboardMarkup(
		inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="pick")]]
	)
	for v in views:
		sent = await callback.message.answer(v["text"], reply_markup=kb_one, parse_mode="HTML")
		subcat_context[sent.message_id] = v["plist"]

# --- парсинг ввода пользователя ---
def _parse_indices(s: str) -> list[int]:
	tokens = re.split(r"[,\s]+", (s or "").strip())
	out = []
	for t in tokens:
		if not t:
			continue
		if "-" in t:
			a, b = t.split("-", 1)
			if a.isdigit() and b.isdigit():
				a, b = int(a), int(b)
				out.extend(range(min(a, b), max(a, b) + 1))
		elif t.isdigit():
			out.append(int(t))
	return sorted(set(out))

# --- добавление в корзину ---
@router.callback_query(F.data == "pick")
async def start_pick(callback: types.CallbackQuery):
	await callback.answer()
	subcat_msg_id = callback.message.message_id
	user_id = callback.from_user.id

	if subcat_msg_id not in subcat_context:
		await callback.message.answer("Не удалось найти список. Откройте категорию заново.")
		return

	prompt = await callback.message.answer("Пришлите номера товаров, например: 1, 3-5, 8")
	pending_add[user_id] = {"subcat": subcat_msg_id, "prompt": prompt.message_id}

@router.message(F.text)
async def pick_numbers(message: types.Message):
	user_id = message.from_user.id
	data = pending_add.get(user_id)
	if not data:
		return

	if message.reply_to_message:
		reply_id = message.reply_to_message.message_id
		if reply_id not in (data["prompt"], data["subcat"]):
			return

	plist = subcat_context.get(data["subcat"], [])
	if not plist:
		await message.answer("Список устарел. Откройте категорию заново.")
		pending_add.pop(user_id, None)
		return

	idxs = _parse_indices(message.text)
	picked = [plist[i - 1] for i in idxs if 0 < i <= len(plist)]
	if not picked:
		await message.answer("Не удалось распознать номера. Пример: 1, 3-5, 8")
		return

	user_cart.setdefault(user_id, []).extend(picked)
	pending_add.pop(user_id, None)

	names = [p.get("название", "Товар") for p in picked][:5]
	more = "" if len(picked) <= 5 else f" и ещё {len(picked) - 5}"
	await message.answer(f"✅ Добавлено: {', '.join(names)}{more}.\nОткройте «🛒 Корзина» в меню.")
