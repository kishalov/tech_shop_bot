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

4. Определи поле "подкатегория" — это тип или серия устройства, но только если она действительно нужна для навигации.

   - "Категория" = бренд или производитель (Apple, Canon, GoPro, Fujifilm, Sony, Samsung, Polaroid, Whoop, Ray Ban и т.д.)
   - "Подкатегория" = тип или серия устройств, если у бренда бывает несколько разных типов товаров (например: у Apple — iPhone / iPad / MacBook).
   - "Модель" = конкретное обозначение версии, поколения или модификации (например: "14 Pro Max", "G7 X Mark III", "HERO12", "mini 12").

   📘 Примеры:
   - "Apple iPhone 14 Pro Max" → категория: Apple, подкатегория: iPhone, модель: 14 Pro Max
   - "Apple MacBook Air M2" → категория: Apple, подкатегория: MacBook, модель: Air M2
   - "Canon PowerShot G7 X Mark III" → категория: Canon, подкатегория: PowerShot, модель: G7 X Mark III
   - "Whoop 5.0 Peak" → категория: Whoop, подкатегория: Без подкатегории, модель: 5.0 Peak
   - "Ray Ban Wayfarer RW4006" → категория: Ray Ban, подкатегория: Без подкатегории, модель: RW4006

   🧩 Правила:
   - Если бренд в целом выпускает один тип устройств (например Whoop делает только браслеты, Ray Ban только очки), подкатегория не нужна → укажи "Без подкатегории".
   - Если у бренда есть несколько направлений (Apple, Samsung, Canon и т.п.), подкатегория нужна, чтобы разделить их.
   - Если слово после бренда явно указывает серию (HERO, PowerShot, Instax mini, iPhone), используй его как подкатегорию.
   - Никогда не ставь конкретную модель (например HERO12, G7 X Mark III) в подкатегорию.
   - Если невозможно определить тип, но видно, что бренд производит один и тот же вид товаров — оставь "Без подкатегории".

5. Если строка выглядит как продолжение предыдущей (например, только цвет и цена без бренда), используй контекст: подставь тот же бренд и тип, что в последней строке с полным названием.

6. Всегда возвращай максимально полные данные. Если в названии товара есть бренд — обязательно продублируй его в `"категория"`.

7. Консистентность:
   - Все товары одного бренда внутри одного сообщения должны иметь одинаковое решение — либо с подкатегориями, либо без них.
   - Если у бренда встречаются разные типы (например смартфоны и ноутбуки) — подкатегории нужны.
   - Если у бренда всё одного типа — подкатегории не нужны вообще.

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

def normalize_brands_and_subcats(items: list[dict]) -> list[dict]:
	"""
	Объединяет похожие бренды и выравнивает подкатегории внутри одного сообщения.
	"""
	from collections import defaultdict
	if not items:
		return items

	# 1. Собираем статистику брендов и подкатегорий
	brand_counts = defaultdict(int)
	for it in items:
		b = (it.get("категория") or "").strip().lower()
		if b:
			brand_counts[b] += 1

	# 2. Определяем основной бренд (наиболее частый)
	main_brand = max(brand_counts, key=brand_counts.get) if brand_counts else ""

	# 3. Подравниваем бренды: все схожие варианты приводим к основному
	for it in items:
		brand = (it.get("категория") or "").strip()
		if not brand or brand.lower() != main_brand:
			it["категория"] = main_brand.capitalize()

	# 4. Анализируем подкатегории
	subcats_by_brand = defaultdict(set)
	for it in items:
		sub = (it.get("подкатегория") or "").strip()
		if sub and sub.lower() not in {"", "без типа", "без подкатегории"}:
			subcats_by_brand[it["категория"]].add(sub)

	# 5. Если у бренда есть несколько разных серий (Kindle, PaperWhite, Scribe) — оставляем их.
	#    Если серия одна — убираем подкатегорию вообще.
	for it in items:
		brand = it["категория"]
		subs = subcats_by_brand.get(brand, set())
		if len(subs) <= 1:
			it["подкатегория"] = ""
		else:
			# если подкатегория пуста, попробуем вывести её из названия
			sub = (it.get("подкатегория") or "").strip()
			if not sub:
				name = (it.get("название товара") or "").lower()
				for s in subs:
					if s.lower() in name:
						it["подкатегория"] = s
						break

	return items

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
		
	results = simplify_subcategories(results)
	print(f"✅ После упрощения подкатегорий: {len(results)}")
	return results

def simplify_subcategories(results: list[dict]) -> list[dict]:
	"""
	Если у бренда только один уникальный тип подкатегории (или все 'Без подкатегории'),
	то убираем подкатегорию вообще — она не нужна для навигации.
	"""
	from collections import defaultdict
	by_brand = defaultdict(list)
	for item in results:
		brand = item.get("категория") or ""
		if brand:
			by_brand[brand].append(item)

	for brand, items in by_brand.items():
		subcats = {it.get("подкатегория", "").lower() for it in items if it.get("подкатегория")}
		# если у бренда одна подкатегория или все без подкатегории — очищаем
		if len(subcats) <= 1 or subcats == {"без подкатегории"}:
			for it in items:
				it["подкатегория"] = ""

	results = normalize_brands_and_subcats(results)
	print(f"✅ После выравнивания брендов/подкатегорий: {len(results)}")
	return results
