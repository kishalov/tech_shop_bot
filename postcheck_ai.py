import os
import json
import asyncio
import re
import gspread
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

google_creds = "/configs/creds.json"
gc = gspread.service_account(filename=google_creds)
sheet = gc.open("Catalog").sheet1

LLM_MODEL = "gpt-4o-mini"
LLM_TIMEOUT = 120
BATCH_SIZE = 20  # меньше = стабильнее

POSTCHECK_PROMPT = """
Ты — интеллектуальный редактор таблицы товаров.

Тебе дан список товаров с полями:
"название товара", "категория", "подкатегория", "модель", "характеристики", "цена".

1. Исправь бренды (поле "категория"), чтобы они были единообразными и корректными.
2. Если написано "Неизвестный бренд", попробуй определить бренд по названию.
3. Не меняй ничего, кроме "категория" и "подкатегория".
4. Верни строго JSON-СПИСОК (array) с теми же объектами, где исправлены только эти поля.
"""


async def check_batch(batch, attempt=1):
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

		reply = getattr(resp.choices[0].message, "content", "").strip()

		# Попробуем разные варианты формата
		try:
			data = json.loads(reply)
		except Exception:
			m = re.search(r"\[.*\]", reply, re.S)
			if m:
				data = json.loads(m.group(0))
			else:
				raise ValueError("Не удалось найти JSON в ответе")

		# Если ответ — словарь с ключами, где лежат объекты, преобразуем в список
		if isinstance(data, dict):
			data = [v for v in data.values() if isinstance(v, dict)]

		if not isinstance(data, list):
			raise ValueError(f"Ответ не список (тип {type(data)})")

		return data

	except Exception as e:
		if attempt < 3:
			print(f"⚠️ Ошибка при постпроверке (попытка {attempt}): {e}")
			await asyncio.sleep(3)
			return await check_batch(batch, attempt + 1)
		else:
			print(f"❌ Не удалось обработать пакет после 3 попыток: {e}")
			return batch


async def postcheck_table():
	print("🧠 Запускаю постпроверку таблицы...")
	headers = sheet.row_values(1)
	all_rows = sheet.get_all_records()
	total = len(all_rows)
	print(f"📊 Найдено строк: {total}")

	changed = 0
	for start in range(0, total, BATCH_SIZE):
		batch = all_rows[start:start + BATCH_SIZE]
		print(f"🔍 Проверяю строки {start + 1}–{min(start + BATCH_SIZE, total)}...")
		checked = await check_batch(batch)

		for i, item in enumerate(checked):
			row_idx = start + i + 2  # +2 = заголовок + индекс
			row_values = [item.get(h, "") for h in headers]
			try:
				sheet.update(f"A{row_idx}:{chr(65 + len(headers) - 1)}{row_idx}", [row_values])
				changed += 1
				await asyncio.sleep(0.6)
			except Exception as e:
				print(f"⚠️ Ошибка обновления строки {row_idx}: {e}")

	print(f"✅ Постпроверка завершена. Обновлено {changed} строк из {total}.")


if __name__ == "__main__":
	asyncio.run(postcheck_table())
