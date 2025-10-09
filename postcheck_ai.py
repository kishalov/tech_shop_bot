import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv
import gspread
from collections import defaultdict

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

google_creds = "/configs/creds.json"
gc = gspread.service_account(filename=google_creds)
sheet = gc.open("Catalog").sheet1

LLM_MODEL = "gpt-4o-mini"
LLM_TIMEOUT = 60


POSTCHECK_PROMPT = """
Ты — интеллектуальный редактор таблицы товаров.

Тебе дан список товаров с полями:
- "название товара"
- "категория" (бренд)
- "подкатегория"
- "модель"
- "характеристики"
- "цена"

Твоя задача:
1. Проверить, чтобы все бренды были написаны одинаково (например, "samsung" → "Samsung").
2. Если у товара указан "Неизвестный бренд", но по названию можно определить бренд — исправь.
3. Не меняй ничего другого, кроме брендов и подкатегорий.
4. Верни исправленные данные в виде JSON списка объектов с теми же полями.

Пример:
[
  {"название товара": "Samsung Galaxy S24", "категория": "Samsung", ...},
  {"название товара": "iPhone 14 Pro", "категория": "Apple", ...}
]
"""


async def check_batch(batch: list[dict]):
	"""Отправка партии товаров в GPT для корректировки брендов"""
	text = json.dumps(batch, ensure_ascii=False)
	messages = [
		{"role": "system", "content": POSTCHECK_PROMPT},
		{"role": "user", "content": f"Вот список товаров для проверки:\n{text}"}
	]

	try:
		resp = await asyncio.wait_for(
			client.chat.completions.create(
				model=LLM_MODEL,
				messages=messages,
				response_format={"type": "json_object"},
			),
			timeout=LLM_TIMEOUT
		)
	except Exception as e:
		print(f"⚠️ Ошибка при постпроверке: {e}")
		return batch

	reply = getattr(resp.choices[0].message, "content", "")
	if not reply.strip():
		return batch

	try:
		data = json.loads(reply)
		if isinstance(data, list):
			return data
		return batch
	except Exception:
		print("⚠️ Не удалось разобрать JSON, пропускаю партию")
		return batch


async def postcheck_table():
	"""Основная функция постпроверки всей таблицы"""
	print("🔍 Загружаю таблицу...")
	headers = sheet.row_values(1)
	all_rows = sheet.get_all_records()
	print(f"📦 Найдено строк: {len(all_rows)}")

	# делим на партии по 50 товаров
	batch_size = 50
	for start in range(0, len(all_rows), batch_size):
		batch = all_rows[start:start + batch_size]
		print(f"🧩 Проверяю строки {start + 1}–{start + len(batch)}...")
		checked = await check_batch(batch)

		# обновляем только если есть отличия
		for i, item in enumerate(checked):
			row_index = start + i + 2  # +2 (заголовок + индекс)
			row_values = [item.get(h, "") for h in headers]
			sheet.update(f"A{row_index}:{chr(65+len(headers)-1)}{row_index}", [row_values])
			await asyncio.sleep(0.5)

	print("✅ Постпроверка завершена.")


if __name__ == "__main__":
	asyncio.run(postcheck_table())
