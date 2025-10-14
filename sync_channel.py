import os
import json
import asyncio
import hashlib
from difflib import SequenceMatcher
from dotenv import load_dotenv
from telethon import TelegramClient
from parser_ai import parse_full_message
import gspread

load_dotenv()

# --- Настройки из .env ---
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
source_channel = os.getenv("SOURCE_CHANNEL")
google_creds = "/configs/creds.json"

CACHE_FILE = "known_items.json"

# --- Google Sheets ---
gc = gspread.service_account(filename=google_creds)
sheet = gc.open("Catalog").sheet1

# --- Подключаемся к Telegram ---
client = TelegramClient("parser_session", api_id, api_hash)


# ---------- УТИЛИТЫ ----------

def _col_letter(n: int) -> str:
	s = ""
	while n > 0:
		n, r = divmod(n - 1, 26)
		s = chr(65 + r) + s
	return s


def make_item_key(item: dict) -> str:
	name = (item.get("название товара") or "").strip().lower()
	char = (item.get("характеристики") or "").strip().lower()
	price = (item.get("цена") or "").strip()
	base = f"{name}:{char}:{price}"
	return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def similar(a: str, b: str) -> float:
	return SequenceMatcher(None, a, b).ratio()


def load_known() -> set[str]:
	if os.path.exists(CACHE_FILE):
		with open(CACHE_FILE, "r", encoding="utf-8") as f:
			try:
				return set(json.load(f))
			except Exception:
				return set()
	return set()


def save_known(known: set[str]):
	with open(CACHE_FILE, "w", encoding="utf-8") as f:
		json.dump(list(known), f, ensure_ascii=False, indent=2)


# ---------- СТРОКА ДЛЯ ДОБАВЛЕНИЯ ----------

def _build_row_for_headers(item: dict, headers: list[str]):
	norm_headers = [h.strip().lower() for h in headers]
	fields = ["название товара", "категория", "характеристики", "цена", "key"]
	idx = {f: (norm_headers.index(f) if f in norm_headers else None) for f in fields}

	if idx["название товара"] is None:
		raise RuntimeError("В таблице нет столбца 'Название товара'")

	existing = [i for i in idx.values() if i is not None]
	first, last = min(existing), max(existing)
	row_buf = [""] * (last - first + 1)

	def put(key: str, value: str):
		i = idx.get(key)
		if i is not None:
			row_buf[i - first] = (value or "").strip()

	for key in fields:
		put(key, item.get(key))

	return row_buf, first + 1, last + 1, idx


# ---------- ГЛАВНАЯ ЛОГИКА ----------

async def process_message(message, headers, all_rows, name_col_norm, key_col_norm, known_keys: set):
	text = message.message
	if not text or len(text) < 20:
		return

	print(f"📩 Обрабатываю сообщение {message.id}...")
	items = await parse_full_message(text)
	if not items:
		return

	for item in items:
		name = (item.get("название товара") or "").strip().lower()
		if not name:
			continue

		item_key = make_item_key(item)
		item["key"] = item_key

		# --- Проверка по ключу ---
		if item_key in known_keys:
			print(f"⏩ Уже добавлен: {item['название товара']}")
			continue

		# --- Проверка похожих названий ---
		is_duplicate = False
		for r in all_rows[1:]:
			if len(r) > name_col_norm:
				existing_name = r[name_col_norm].strip().lower()
				if existing_name and similar(name, existing_name) > 0.9:
					print(f"⚠️ Похожий товар уже есть: {name}")
					is_duplicate = True
					break
		if is_duplicate:
			continue

		row_buf, c1, c2, idx = _build_row_for_headers(item, headers)

		# --- Проверка существующей строки по ключу (на случай обновления цены) ---
		found_row = None
		for i, r in enumerate(all_rows[1:], start=2):
			if key_col_norm is not None and len(r) > key_col_norm:
				if r[key_col_norm].strip() == item_key:
					found_row = i
					break

		if found_row:
			existing_row = all_rows[found_row - 1]
			existing_price = existing_row[idx["цена"]] if len(existing_row) > idx["цена"] else ""
			new_price = (item.get("цена") or "").strip()
			if new_price and new_price != existing_price:
				update_data = existing_row[:]
				if len(update_data) <= idx["цена"]:
					update_data.extend([""] * (idx["цена"] - len(update_data) + 1))
				update_data[idx["цена"]] = new_price
				range_str = f"{_col_letter(c1)}{found_row}:{_col_letter(c2)}{found_row}"
				sheet.update(range_str, [update_data[c1 - 1:c2]])
				print(f"💰 Обновлена цена: {item['название товара']} ({existing_price} → {new_price})")
			else:
				print(f"⏩ Без изменений: {item['название товара']}")
		else:
			sheet.append_row(row_buf, table_range=f"{_col_letter(c1)}1:{_col_letter(c2)}1")
			print(f"✅ Добавлено новое: {item['название товара']}")
			all_rows.append([""] * len(headers))
			known_keys.add(item_key)
			save_known(known_keys)

		await asyncio.sleep(0.3)


async def main():
	await client.start()
	print(f"🔍 Читаю посты из канала @{source_channel}...")

	headers = sheet.row_values(1)

	# --- если столбца key нет — добавляем ---
	if "key" not in [h.strip().lower() for h in headers]:
		sheet.update_cell(1, len(headers) + 1, "key")
		headers.append("key")
		print("🆕 Добавлен столбец 'key' в таблицу.")

	all_rows = sheet.get_all_values()
	norm_headers = [h.strip().lower() for h in headers]
	name_col_norm = norm_headers.index("название товара")
	key_col_norm = norm_headers.index("key")

	known_keys = load_known()
	print(f"📚 Загружено известных ключей: {len(known_keys)}")

	async for message in client.iter_messages(source_channel, limit=None, reverse=True):
		await process_message(message, headers, all_rows, name_col_norm, key_col_norm, known_keys)

	print("✅ Парсинг завершён. Все данные добавлены в таблицу.")


async def weekly_job():
	while True:
		print("🕓 Запускаю еженедельный прогон...")
		try:
			await main()
		except Exception as e:
			print(f"⚠️ Ошибка во время прогона: {e}")
		print("💤 Ожидание 7 дней до следующего прогона...")
		await asyncio.sleep(7 * 24 * 60 * 60)


if __name__ == "__main__":
	asyncio.run(weekly_job())
