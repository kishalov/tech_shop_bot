from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import defaultdict
from sheets import get_products
import re
import time

REFRESH_SECONDS = 600  # собираем каталог раз в 10 минут
CAT_CACHE: dict = {"built_at": 0, "by_category": {}}

router = Router()

# --- конфиг / константы ---
MAX_TG_LEN = 4000  # чуть ниже 4096

# --- память ---
user_cart: dict[int, list[dict]] = {}
subcat_context: dict[int, list[dict]] = {}  # message_id -> товары этой подкатегории
# кто из пользователей сейчас «добавляет» и к какому сообщению
# user_id -> {"subcat": <message_id списка>, "prompt": <message_id промпта>}
pending_add: dict[int, dict] = {}

# --- отображение одной строки товара ---
INLINE_ORDER = ["название", "бренд", "цвет", "сила", "описание", "цена"]


# --- группировки ---
def group_by_category(products: list[dict]) -> dict[str, list[dict]]:
	grouped = defaultdict(list)
	for p in products:
		grouped[p.get("категория") or "Без категории"].append(p)
	return grouped


def _group_by_subcategory(items: list[dict]) -> dict[str, list[dict]]:
	"""
	Группирует товары по подкатегориям, но не показывает «Без подкатегории».
	Все такие товары попадают в общий блок "__NO_SUBCAT__".
	"""
	grouped = defaultdict(list)
	for p in items:
		sub = (p.get("подкатегория") or "").strip()
		if sub and sub.lower() not in {"", "Без подкатегории", "Без типа"}:
			grouped[sub].append(p)
		else:
			grouped["__NO_SUBCAT__"].append(p)
	return dict(sorted(grouped.items(), key=lambda kv: kv[0].lower() if kv[0] != "__NO_SUBCAT__" else ""))


def _format_item_one_line(p: dict) -> str:
	parts: list[str] = []
	for key in INLINE_ORDER:
		val = (p.get(key) or "").strip()
		if val:
			parts.append(val)
	# добираем остальные поля, если есть
	skip = set(INLINE_ORDER + ["фото", "категория", "бренд"])
	for k, v in p.items():
		v = (v or "").strip()
		if v and k not in skip:
			parts.append(v)
	return " | ".join(parts)


def _build_catalog_views(products: list[dict]) -> dict[str, list[dict]]:
	"""
	Создаёт структуру {категория: [списки подкатегорий]} для отображения каталога.
	Если у категории нет подкатегорий — выводит товары одним блоком.
	"""
	by_cat: dict[str, list[dict]] = {}
	cats = group_by_category(products)
	for cat, items in cats.items():
		groups = _group_by_subcategory(items)
		views = []
		for subcat, plist in groups.items():
			lines = [f"{i}) {_format_item_one_line(p)}" for i, p in enumerate(plist, start=1)]
			# если нет подкатегории — просто список без заголовка
			text = "\n".join(lines) if subcat == "__NO_SUBCAT__" else f"▶ {subcat}\n\n" + "\n".join(lines)
			if len(text) > MAX_TG_LEN:
				text = text[:MAX_TG_LEN - 1] + "…"
			views.append({"subcat": subcat, "text": text, "plist": plist})
		by_cat[cat] = views
	return by_cat


def ensure_catalog_warm(force: bool = False):
	"""Если кэш пустой или устарел — перечитать таблицу и собрать тексты."""
	now = time.time()
	if (not force) and CAT_CACHE["by_category"] and (now - CAT_CACHE["built_at"] < REFRESH_SECONDS):
		return
	products = get_products()  # тут уже есть внутренний TTL из sheets.py
	CAT_CACHE["by_category"] = _build_catalog_views(products)
	CAT_CACHE["built_at"] = now


# --- меню каталога: сразу категории ---
async def show_catalog_menu(message: types.Message):
	ensure_catalog_warm()  # прогреем при открытии меню
	cats = list(CAT_CACHE["by_category"].keys())

	kb = InlineKeyboardBuilder()
	for cat in cats:
		kb.button(text=cat, callback_data=f"cat:{cat}")
	kb.adjust(2)
	await message.answer("📂 Выберите категорию:", reply_markup=kb.as_markup())


# --- показать товары категории: подкатегории по одному сообщению ---
@router.callback_query(lambda c: c.data.startswith("cat:"))
async def show_products(callback: types.CallbackQuery):
	await callback.answer()
	_, value = callback.data.split(":", 1)

	ensure_catalog_warm()  # на всякий случай

	views = CAT_CACHE["by_category"].get(value, [])

	# заголовок категории
	try:
		await callback.message.edit_text(f"📦 Категория: {value}")
	except Exception:
		await callback.message.answer(f"📦 Категория: {value}")

	kb_one = InlineKeyboardMarkup(
		inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="pick")]]
	)

	for v in views:
		sent = await callback.message.answer(v["text"], reply_markup=kb_one)
		subcat_context[sent.message_id] = v["plist"]  # контекст для «пикера»


# --- парсинг "1, 3-5, 8" ---
def _parse_indices(s: str) -> list[int]:
	tokens = re.split(r"[,\s]+", (s or "").strip())
	out: list[int] = []
	for t in tokens:
		if not t:
			continue
		if "-" in t:
			a, b = t.split("-", 1)
			if a.isdigit() and b.isdigit():
				a, b = int(a), int(b)
				lo, hi = (a, b) if a <= b else (b, a)
				out.extend(range(lo, hi + 1))
		elif t.isdigit():
			out.append(int(t))
	return sorted(set(out))


# --- старт добавления (нажата "➕ Добавить") ---
@router.callback_query(F.data == "pick")
async def start_pick(callback: types.CallbackQuery):
	await callback.answer()
	subcat_msg_id = callback.message.message_id
	user_id = callback.from_user.id

	if subcat_msg_id not in subcat_context:
		await callback.message.answer("Не удалось найти список этой подкатегории. Откройте категорию заново.")
		return

	# Просто текст без ForceReply — меню не пропадает
	prompt = await callback.message.answer(
		"Пришлите номера товаров из списка, например: 1, 3-5, 8"
	)

	pending_add[user_id] = {"subcat": subcat_msg_id, "prompt": prompt.message_id}


# --- принять номера в ответ на ForceReply ---
@router.message(F.text)
async def pick_numbers(message: types.Message):
	user_id = message.from_user.id
	data = pending_add.get(user_id)
	if not data:
		return  # сейчас нет режима добавления

	# если это реплай — проверим, что реплай на нужное сообщение
	if message.reply_to_message:
		reply_id = message.reply_to_message.message_id
		if reply_id not in (data["prompt"], data["subcat"]):
			return  # пользователь ответил не туда

	plist = subcat_context.get(data["subcat"], [])
	if not plist:
		await message.answer("Список этой подкатегории устарел. Откройте категорию заново.")
		pending_add.pop(user_id, None)
		return

	idxs = _parse_indices(message.text)
	picked = []
	for i in idxs:
		j = i - 1
		if 0 <= j < len(plist):
			picked.append(plist[j])

	if not picked:
		await message.answer("Не разобрал номера. Пример: 1, 3-5, 8")
		return

	user_cart.setdefault(user_id, []).extend(picked)
	pending_add.pop(user_id, None)

	names = [p.get("название", "Товар") for p in picked][:5]
	more = "" if len(picked) <= 5 else f" и ещё {len(picked) - 5}"
	await message.answer(f"✅ Добавлено: {', '.join(names)}{more}.\nОткройте «🛒 Корзина» в меню.")
