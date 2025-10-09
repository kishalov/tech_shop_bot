import os, re, json, asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

LLM_MODEL = "gpt-4o-mini"
LLM_TIMEOUT = 30
LLM_MAX_CONCURRENCY = 5
LLM_MAX_RETRIES = 3

PRICE_RE = re.compile(r'(?P<price>-?\d{1,3}[.,]\d{3})(?!\d)', re.IGNORECASE)
EMOJI_RE = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)

SINGLE_LINE_SYSTEM_PROMPT = """Ты — интеллектуальный парсер товаров... (оставь как есть)"""

def normalize_price(s: str) -> str:
	nums = re.findall(r"\d+", s.replace(",", "").replace(".", "").replace(" ", ""))
	if not nums: return ""
	raw = "".join(nums)
	try:
		return f"{int(raw):,} ₽".replace(",", " ")
	except: return ""

def has_price_like(text: str): return bool(PRICE_RE.search(text))

def _stitch_candidates(full_text: str) -> list[str]:
	lines = [EMOJI_RE.sub("", l).strip() for l in full_text.splitlines() if l.strip()]
	candidates, i = [], 0
	while i < len(lines):
		line = lines[i]
		if PRICE_RE.search(line):
			candidates.append(line)
			i += 1
		else:
			for span in (1,2):
				if i+span < len(lines):
					joined = " ".join(lines[i:i+span+1])
					if PRICE_RE.search(joined):
						candidates.append(joined)
						i += span+1
						break
			else: i += 1
	return candidates

async def _parse_line_with_gpt(line: str, context_before="", context_after=""):
	msgs = [
		{"role": "system", "content": SINGLE_LINE_SYSTEM_PROMPT},
		{"role": "user", "content": f"{context_before}\n\n{line.strip()}"}
	]
	try:
		resp = await asyncio.wait_for(
			client.chat.completions.create(model=LLM_MODEL, messages=msgs, response_format={"type":"json_object"}),
			timeout=LLM_TIMEOUT
		)
		data = json.loads(resp.choices[0].message.content)
		return data if isinstance(data, dict) else None
	except: return None

async def _safe_parse_line(lines, i, sem):
	line = lines[i]
	context_before = "\n".join(lines[max(0,i-2):i])
	context_after = "\n".join(lines[i+1:i+3])
	for _ in range(LLM_MAX_RETRIES):
		async with sem:
			res = await _parse_line_with_gpt(line, context_before, context_after)
		if res: return res
		await asyncio.sleep(0.5)
	return None

async def parse_full_message(text: str) -> list[dict]:
	if not has_price_like(text): return []
	cands = _stitch_candidates(text)
	if not cands: return []

	sem = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
	parsed = await asyncio.gather(*[asyncio.create_task(_safe_parse_line(cands, i, sem)) for i in range(len(cands))])

	results, seen = [], set()
	for item in parsed:
		if not item: continue
		name = (item.get("название товара") or "").strip()
		price = normalize_price(item.get("цена",""))
		if not name or not price: continue
		key = (name.lower(), price)
		if key in seen: continue
		seen.add(key)
		results.append({
			"название товара": name,
			"категория": (item.get("категория") or "").strip(),
			"подкатегория": (item.get("подкатегория") or "").strip(),
			"цвет": (item.get("цвет") or "").strip(),
			"модель": (item.get("модель") or "").strip(),
			"характеристики": (item.get("характеристики") or "").strip(),
			"цена": price
		})
	results = _cleanup_subcats(results)
	return results

def _cleanup_subcats(items: list[dict]) -> list[dict]:
	from collections import defaultdict
	by_brand = defaultdict(list)
	for it in items: by_brand[it.get("категория","")].append(it)
	for brand, group in by_brand.items():
		subs = { (it.get("подкатегория") or "").lower() for it in group if it.get("подкатегория") }
		if len(subs) <= 1 or subs == {"без подкатегории"}:
			for it in group: it["подкатегория"] = ""
	return items
