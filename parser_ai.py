import os
import re
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=api_key)

# ------------------ НАСТРОЙКИ ------------------

LLM_MODEL = "gpt-4o-mini"   # устойчивее на длинных списках
LLM_TIMEOUT = 30             # сек на один запрос
LLM_MAX_CONCURRENCY = 5      # одновременно запросов к LLM
LLM_MAX_RETRIES = 3          # ретраи на строку

# Цена: строго форматы "-20.000", "20.000", "-20,000", "20,000"
PRICE_RE = re.compile(
	r'(?P<price>-?\d{1,3}[.,]\d{3})(?!\d)',  # число с 1–3 цифрами, затем запятая/точка и ещё 3 цифры
	re.IGNORECASE
)
EMOJI_RE = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)

# Системный промпт: ОДНА строка → ОДИН объект
SINGLE_LINE_SYSTEM_PROMPT = """
Ты — интеллектуальный парсер товаров из Telegram-поста о продаже техники и электроники.

Твоя задача — извлекать ТОЛЬКО реальные товары, которые предлагаются к продаже или упоминаются как позиции с ценой.
Игнорируй справочные, обучающие или описательные тексты (например, технические спецификации, описание моделей, стран, ограничений, функций и т.д.).

На вход подаются строки (или небольшие блоки) текста. Твоя задача — вернуть ровно один объект JSON вида:

{
  "название товара": "",
  "категория": "",
  "подкатегория": "",
  "цвет": "",
  "модель": "",
  "характеристики": "",
  "цена": ""
}

---
🧭 Логика:

1. Строка описывает товар, если в ней указана цена и есть слова, похожие на название модели, бренда или устройства.

2. Если в строке есть название, которое выглядит как бренд (название перед моделью — например "Canon PowerShot", "GoPro HERO12", "Fujifilm Instax"), считай это **брендом** и запиши его в поле `"категория"`.

3. Если явного бренда нет, но в названии присутствует узнаваемая модель (например, "A16", "HERO13", "Instax mini 12", "PowerShot"), попробуй определить бренд по известным шаблонам моделей. Если модели не существует ни у одного из известных брендов — оставь `"Неизвестный бренд"`.

4. Поле "подкатегория" определяется по структуре сообщения — по строкам, которые выглядят как заголовки разделов.
   Не придумывай подкатегорию по типу устройства (например, "смартфон", "камера", "дрон").
   Если в сообщении нет таких строк-заголовков, укажи "Без типа".

5. Если строка выглядит как продолжение предыдущей (например, только цвет и цена без бренда), используй контекст: подставь тот же бренд и тип, что в последней строке с полным названием.

6. Всегда возвращай максимально полные данные. Если в названии товара есть бренд — обязательно продублируй его в `"категория"`.

тавь это вместо текущих пунктов — оно сохранит строгую логику, но позволит GPT снова определять подкатегории корректно.

4. Поле "подкатегория" определяется по структуре сообщения — по строкам, которые выглядят как заголовки разделов.
   Не придумывай подкатегорию по типу устройства (например, "смартфон", "камера", "дрон").
   Если в сообщении нет таких строк-заголовков, укажи "Без типа".

7. Определи подкатегорию по структуре сообщения:
   - Заголовком подкатегории считается любая строка, которая:
       • стоит отдельно (перед группой товаров);
       • не содержит цен, чисел или валют;
       • содержит 1–5 слов (например: "GoPro", "Oura Rings", "Whoop", "Camera 📸", "Redmi Phones");
       • может включать эмодзи, ссылки, флаги или текст в скобках (их нужно игнорировать);
       • может быть записана ЗАГЛАВНЫМИ буквами.
   - Все товары, идущие после такой строки, относятся к этой подкатегории, пока не встретится новая строка-заголовок.
   - Если таких строк несколько (например, "GoPro" и затем "Camera"), последняя из них заменяет текущую подкатегорию.

8. Очистка подкатегорий:
   - Удали эмодзи, флаги, ссылки, скобки и лишние символы.
   - Приведи подкатегорию к нормальному виду: первая буква заглавная, остальные строчные
     (например: "GoPro", "Whoop", "Camera", "Oura Rings").
   - Если строка полностью в верхнем регистре ("PLAID NOTE"), приведи её к обычному виду ("Plaid Note").

9. Если подкатегория не найдена даже после анализа структуры — укажи "Без типа".

"""

# ------------------ ПОМОЩНИКИ ------------------

def _stitch_candidates(full_text: str) -> list[str]:
    """
    Собираем КАНДИДАТ-СТРОКИ: читаем ВСЁ сообщение и формируем строки,
    в которых встречается цена. Чтобы не потерять товары, у которых
    название и цена разнесены по соседним строкам, пытаемся склеить 1-2
    последующие строки, если первая без цены, а следующая содержит цену.
    """
    raw_lines = [EMOJI_RE.sub("", l).strip() for l in full_text.splitlines()]
    raw_lines = [l for l in raw_lines if l]  # убираем пустые

    candidates = []
    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        if PRICE_RE.search(line):
            candidates.append(line)
            i += 1
            continue

        # Пытаемся склеить с 1–2 следующими строками, если там появится цена
        made = False
        for span in (1, 2):
            if i + span < n:
                combo = " ".join(raw_lines[i:i+span+1])
                if PRICE_RE.search(combo):
                    candidates.append(combo)
                    i += span + 1
                    made = True
                    break
        if not made:
            i += 1

    return candidates

# --- форматирование цены ---
def normalize_price(s: str) -> str:
	nums = re.findall(r"\d+", s.replace(",", "").replace(".", "").replace(" ", ""))
	if not nums:
		return ""
	raw = "".join(nums)
	try:
		price = int(raw)
		return f"{price:,} ₽".replace(",", " ")
	except ValueError:
		return ""

# --- фильтрация валидных товаров ---
def is_valid_item(item: dict) -> bool:
	name = item.get("название товара", "").strip()
	if not name or len(name) < 3:
		return False
	if any(x in name.lower() for x in ["доставка", "распродажа", "акция", "новинки", "скидка", "гарантия"]):
		return False
	if not item.get("цена"):
		return False
	return True

async def _parse_line_with_gpt(line: str, context_before: str = "", context_after: str = "") -> dict | None:
	"""
	Парсим ОДНУ строку через GPT с учётом соседнего контекста.
	"""
	context_text = ""
	if context_before or context_after:
		context_text = (
			"Контекст:\n"
			f"До этой строки было:\n{context_before.strip()}\n\n"
			f"После этой строки идёт:\n{context_after.strip()}\n\n"
			"Если это просто часть описания (например, емкость, цвета, регионы, ограничения, "
			"модели, коды и т.п.), и нет явной цены — НЕ считай это товаром.\n"
		)

	messages = [
		{"role": "system", "content": SINGLE_LINE_SYSTEM_PROMPT},
		{"role": "user", "content": context_text + f"А теперь проанализируй строку:\n{line.strip()}"}
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
	except asyncio.TimeoutError:
		return None
	except Exception as e:
		print(f"⚠️ LLM error: {e}")
		return None

	reply = getattr(resp.choices[0].message, "content", None)
	if not reply or not reply.strip():
		return None

	try:
		data = json.loads(reply)
		if isinstance(data, list):
			data = data[0] if data else None
		if not isinstance(data, dict):
			return None
		return data
	except Exception:
		m = re.search(r"\{.*\}", reply, re.S)
		if not m:
			return None
		try:
			return json.loads(m.group(0))
		except Exception:
			return None

async def _safe_parse_line(lines: list[str], index: int, sem: asyncio.Semaphore) -> dict | None:
	"""
	Пытаемся разобрать строку с контекстом.
	"""
	line = lines[index]
	context_before = "\n".join(lines[max(0, index - 2): index])
	context_after = "\n".join(lines[index + 1: index + 3])

	for attempt in range(LLM_MAX_RETRIES):
		async with sem:
			parsed = await _parse_line_with_gpt(line, context_before, context_after)
		if parsed:
			return parsed
		await asyncio.sleep(0.3 * (attempt + 1))

	# fallback
	m = PRICE_RE.search(line)
	if not m:
		return None
	raw_price = m.group("price")
	price_norm = normalize_price(raw_price)
	name = re.sub(r'\s*[-–—:]\s*$', "", line[:m.start()].strip())
	if len(name) < 2:
		return None
	return {
		"название товара": name,
		"категория": "",
		"подкатегория": "",
		"цвет": "",
		"модель": "",
		"характеристики": "",
		"цена": price_norm or raw_price,
	}

# ------------------ ГЛАВНАЯ ФУНКЦИЯ ------------------

def has_price_like(text: str) -> bool:
	"""
	Возвращает True, если в тексте встречается цена только в формате:
	-20.000 / 20.000 / -20,000 / 20,000
	"""
	return bool(PRICE_RE.search(text))

async def _safe_parse_line(lines: list[str], index: int, sem: asyncio.Semaphore) -> dict | None:
	"""
	Пытаемся разобрать строку с контекстом.
	"""
	line = lines[index]
	context_before = "\n".join(lines[max(0, index - 2): index])
	context_after = "\n".join(lines[index + 1: index + 3])

	for attempt in range(LLM_MAX_RETRIES):
		async with sem:
			parsed = await _parse_line_with_gpt(line, context_before, context_after)
		if parsed:
			return parsed
		await asyncio.sleep(0.3 * (attempt + 1))

	# fallback — только если есть реальная цена
	m = PRICE_RE.search(line)
	if not m:
		return None  # без цены ничего не создаём
	raw_price = m.group("price")
	price_norm = normalize_price(raw_price)
	name = re.sub(r'\s*[-–—:]\s*$', "", line[:m.start()].strip())
	if len(name) < 2:
		return None
	return {
		"название товара": name,
		"категория": "",
		"подкатегория": "",
		"цвет": "",
		"модель": "",
		"характеристики": "",
		"цена": price_norm or raw_price,
	}


async def parse_full_message(text: str) -> list[dict]:
	"""
	1) Проверяет, содержит ли сообщение что-то похожее на цену.
	2) Если нет — сразу пропускает (чтобы не парсить справочную информацию).
	3) Выделяет кандидатов со строками, где есть цены.
	4) Прогоняет каждую строку через GPT.
	5) Нормализует и фильтрует товары.
	"""
	# 🔹 Пропускаем сообщения без ценоподобных выражений
	if not has_price_like(text):
		print("⏩ Сообщение не содержит цен — пропускаю полностью.")
		return []

	candidates = _stitch_candidates(text)
	print(f"🔎 Кандидатов-строк: {len(candidates)}")

	if not candidates:
		print("⏩ Не найдено строк с ценами — пропускаю сообщение.")
		return []

	sem = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
	tasks = [asyncio.create_task(_safe_parse_line(candidates, i, sem)) for i in range(len(candidates))]
	parsed = await asyncio.gather(*tasks)

	results: list[dict] = []
	seen = set()  # защита от дублей (name+price)

	for item in parsed:
		if not item:
			continue

		# нормализуем цену
		if item.get("цена"):
			item["цена"] = normalize_price(str(item["цена"])) or str(item["цена"])

		name = (item.get("название товара") or "").strip()
		price = (item.get("цена") or "").strip()
		if not name or not price:
			continue

		key = (name.lower(), price)
		if key in seen:
			continue
		seen.add(key)

		results.append({
			"название товара": name,
			"категория": item.get("категория", "").strip(),
			"подкатегория": item.get("подкатегория", "").strip(),
			"цвет": item.get("цвет", "").strip(),
			"модель": item.get("модель", "").strip(),
			"характеристики": item.get("характеристики", "").strip(),
			"цена": price,
		})

	print(f"✅ Всего товаров из сообщения: {len(results)}")
	return results
