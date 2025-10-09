import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from parser_ai import parse_full_message
import gspread

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
source_channel = os.getenv("SOURCE_CHANNEL")
google_creds = "/configs/creds.json"

gc = gspread.service_account(filename=google_creds)
sheet = gc.open("Catalog").sheet1
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
	existing = [i for i in idx.values() if i is not None]
	first, last = min(existing), max(existing)
	row_buf = [""] * (last - first + 1)

	for f in fields:
		i = idx.get(f)
		if i is not None:
			row_buf[i - first] = (item.get(f, "") or "").strip()

	return row_buf, first + 1, last + 1


def _find_first_empty_row(sheet):
	rows = sheet.get_all_values()
	for i, row in enumerate(rows, start=1):
		if not any(cell.strip() for cell in row):
			return i
	return len(rows) + 1


async def process_message(message, headers, all_rows, name_col_norm):
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

		row_buf, c1, c2 = _build_row_for_headers(item, headers)
		found_row = None

		for i, r in enumerate(all_rows[1:], start=2):
			val = r[name_col_norm].strip().lower() if len(r) > name_col_norm else ""
			if val == name:
				found_row = i
				break

		if found_row:
			range_str = f"{_col_letter(c1)}{found_row}:{_col_letter(c2)}{found_row}"
			sheet.update(range_str, [row_buf])
			print(f"♻️ Обновлено: {item['название товара']}")
		else:
			row_num = _find_first_empty_row(sheet)
			range_str = f"{_col_letter(c1)}{row_num}:{_col_letter(c2)}{row_num}"
			sheet.update(range_str, [row_buf])
			print(f"✅ Добавлено новое: {item['название товара']}")
			all_rows = sheet.get_all_values()

		await asyncio.sleep(0.5)


async def main():
	await client.start()
	print(f"🔍 Читаю посты из канала @{source_channel}...")

	headers = sheet.row_values(1)
	all_rows = sheet.get_all_values()
	name_col_norm = [h.strip().lower() for h in headers].index("название товара")

	async for message in client.iter_messages(source_channel, limit=None, reverse=False):
		await process_message(message, headers, all_rows, name_col_norm)

	print("✅ Прогон завершён.")


if __name__ == "__main__":
	asyncio.run(main())
