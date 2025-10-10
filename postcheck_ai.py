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
BATCH_SIZE = 20  # оптимально для точности

# --- допустимые категории ---
VALID_CATEGORIES = [
	"iPhone SE / 11 / 12",
	"iPhone 13",
	"iPhone 14 / 14 Pro",
	"iPhone 15 / 15 Pro",
	"iPhone 16e / 16",
	"iPhone 16 Pro",
	"iPhone 17 / Air",
	"iPhone 17 Pro / Pro Max",
	"iPad Air",
	"iPad Pro",
	"iPad / iPad mini",
	"iMac",
	"MacBook Air",
	"MacBook Pro",
	"AirPods",
	"Apple Watch",
	"Яндекс / JBL",
	"PS 5 / Xbox",
	"Huawei / Honor",
	"Pixel / One Plus",
	"Samsung",
	"Xiaomi / Poco",
	"Dyson",
	"DJi",
	"Смарт-часы",
	"Наушники",
	"Аксессуары",
	"Гаджеты",
	"Fix / Labubu"
]

# --- системный промпт ---
POSTCHECK_PROMPT = f"""
Ты — интеллектуальный редактор таблицы товаров.

Каждый объект содержит поля:
"название товара", "категория", "характеристики", "цена".

Твоя задача — проверить и, если нужно, исправить поле "категория", чтобы оно точно соответствовало одному из допустимых вариантов.

1. Используй только следующие категории (никаких новых не придумывай):
{json.dumps(VALID_CATEGORIES, ensure_ascii=False, indent=2)}

2. Если категория пуста, ошибочна или не из списка — подбери правильную по названию товара.
3. Если бренд невозможно определить с уверенностью, оставь категорию пустой.
4. Ничего, кроме поля "категория", не меняй.
5. Сохраняй порядок элементов и верни JSON-список того же размера.
"""

# --- утилиты ---

def need_check(item: dict) -> bool:
	"""Определяет, нужно ли отправлять строку на проверку"""
	cat = (item.get("категория") or "").strip()
	name = (item.get("название товара") or "").strip()
	if not name:
		return False
	return not cat or cat not in VALID_CATEGORIES


async def check_batch(batch, attempt=1):
	"""Проверка одного батча"""
	text = json.dumps(batch, ensure_ascii=False)
	messages = [
		{"role": "system", "content": POSTCHECK_PROMPT},
		{"role": "user", "content": f"Вот часть таблицы для проверки категорий (несколько строк подряд):\n{text}"}
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
		try:
			data = json.loads(reply)
		except Exception:
			m = re.search(r"\[.*\]", reply, re.S)
			if not m:
				raise ValueError("Не удалось найти JSON в ответе")
			data = json.loads(m.group(0))

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


async def postcheck_table(limit_rows: int | None = None):
	"""Основная функция постпроверки категорий"""
	print("🧠 Запускаю постпроверку категорий...")
	headers = sheet.row_values(1)
	all_rows = sheet.get_all_records()
	total = len(all_rows)
	if limit_rows:
		total = min(total, limit_rows)

	print(f"📊 Проверяется {total} строк.")
	changed = 0

	for start in range(0, total, BATCH_SIZE):
		batch = all_rows[start:start + BATCH_SIZE]
		to_check = [r for r in batch if need_check(r)]
		if not to_check:
			continue

		print(f"🔍 Проверяю строки {start + 1}–{min(start + BATCH_SIZE, total)}...")
		checked = await check_batch(to_check)

		for item in checked:
			old_item = next((r for r in batch if r["название товара"] == item["название товара"]), None)
			if not old_item:
				continue

			new_cat = (item.get("категория") or "").strip()
			old_cat = (old_item.get("категория") or "").strip()
			if new_cat == old_cat:
				continue

			try:
				row_idx = all_rows.index(old_item) + 2  # +2 = заголовок + индекс
				col_idx = headers.index("категория") + 1
				sheet.update_cell(row_idx, col_idx, new_cat)
				changed += 1
				print(f"♻️ Исправлена категория для: {old_item['название товара']} → {new_cat}")
				await asyncio.sleep(0.5)
			except Exception as e:
				print(f"⚠️ Ошибка обновления строки: {e}")

	print(f"✅ Постпроверка завершена. Исправлено {changed} категорий из {total} строк.")


if __name__ == "__main__":
	asyncio.run(postcheck_table(limit_rows=200))
