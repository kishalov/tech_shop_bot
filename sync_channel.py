import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from parser_ai import parse_full_message, global_postprocess
import gspread

load_dotenv()

# --- Настройки из .env ---
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
source_channel = os.getenv("SOURCE_CHANNEL")
google_creds = "/configs/creds.json"

# --- Google Sheets ---
gc = gspread.service_account(filename=google_creds)
sheet = gc.open("Catalog").sheet1

# --- Подключаемся к Telegram ---
client = TelegramClient("parser_session", api_id, api_hash)


def _col_letter(n: int) -> str:
	s = ""
	while n > 0:
		n, r = divmod(n - 1, 26)
		s = chr(65 + r) + s
	return s


def _build_row_for_headers(item: dict, headers: list[str]):
	norm_headers = [h.strip().lower() for h in headers]
	fields = ["название товара", "категория", "подкатегория", "цвет", "модель", "характеристики", "цена"]
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

	return row_buf, first + 1, last + 1


async def process_message(message, headers, all_rows, name_col_norm):
	text = message.message
	if not text or len(text) < 20:
		return

	print(f"📩 Обрабатываю сообщение {message.id}...")
	items = await parse_full_message(text)
	if not items:
		return

	unique_names = set()
	for item in items:
		name = item.get("название товара", "").strip().lower()
		if not name or name in unique_names:
			continue
		unique_names.add(name)

		row_buf, c1, c2 = _build_row_for_headers(item, headers)

		# поиск строки по названию
		found_row = None
		for i, r in enumerate(all_rows[1:], start=2):
			val = r[name_col_norm].strip().lower() if len(r) > name_col_norm else ""
			if val == name:
				found_row = i
				break

		range_str = f"{_col_letter(c1)}{found_row or len(all_rows)+1}:{_col_letter(c2)}{found_row or len(all_rows)+1}"

		if found_row:
			sheet.update(range_str, [row_buf])
			print(f"♻️ Обновлено: {item['название товара']}")
		else:
			sheet.append_row(row_buf, table_range=f"{_col_letter(c1)}1:{_col_letter(c2)}1")
			print(f"✅ Добавлено новое: {item['название товара']}")
			all_rows.append([""] * len(headers))

		await asyncio.sleep(0.5)  # не перегружаем API


async def main():
	await client.start()
	print(f"🔍 Читаю посты из канала @{source_channel}...")

	headers = sheet.row_values(1)
	all_rows = sheet.get_all_values()
	name_col_norm = [h.strip().lower() for h in headers].index("название товара")

	all_items = []

	# 1️⃣ Собираем товары
	async for message in client.iter_messages(source_channel, limit=None, reverse=True):
		text = message.message
		if not text or len(text) < 20:
			continue

		print(f"📩 Обрабатываю сообщение {message.id}...")
		items = await parse_full_message(text)
		if not items:
			continue
		all_items.extend(items)

		await asyncio.sleep(0.5)

	print(f"🔧 Запускаю глобальную нормализацию на {len(all_items)} товаров...")
	all_items = global_postprocess(all_items)
	print("✅ Глобальная нормализация завершена.")

	# 2️⃣ Записываем товары в Google Sheets
	for item in all_items:
		row_buf, c1, c2 = _build_row_for_headers(item, headers)
		sheet.append_row(row_buf, value_input_option="USER_ENTERED")
		print(f"✅ Добавлено: {item['название товара']}")
		await asyncio.sleep(0.4)

	print("✅ Прогон завершён.")

async def daily_job():
	while True:
		print("🕓 Запускаю ежедневный прогон...")
		try:
			await main()
		except Exception as e:
			print(f"⚠️ Ошибка во время прогона: {e}")
		print("💤 Ожидание 24 часа до следующего прогона...")
		await asyncio.sleep(24 * 60 * 60)  # 24 часа


if __name__ == "__main__":
	asyncio.run(daily_job())
