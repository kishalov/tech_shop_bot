import os
import gspread
import time
import re

# --- путь до creds.json ---
server_path = "/configs/creds.json"
local_path = os.path.join(os.path.dirname(__file__), "configs", "creds.json")
creds_path = server_path if os.path.exists(server_path) else local_path

gc = gspread.service_account(filename=creds_path)

# Кэш (5 минут)
_cache = {"products": [], "last_update": 0}

# --- нормализация заголовков ---
HEADER_ALIASES = {
	"name": "название",
	"product": "название",
	"название": "название",
	"название товара": "название",

	"price": "цена",
	"стоимость": "цена",
	"цена": "цена",

	"category": "категория",
	"категория": "категория",

	"description": "характеристики",
	"описание": "характеристики",
	"характеристики": "характеристики",
}

def _norm(s: str) -> str:
	return re.sub(r"\s+", " ", (s or "")).strip().lower()


def get_products(sheet_name: str = "Catalog", ttl: int = 300) -> list[dict]:
	"""Читает гугл-таблицу и возвращает список товаров"""
	now = time.time()
	if _cache["products"] and now - _cache["last_update"] <= ttl:
		return _cache["products"]

	sh = gc.open(sheet_name)
	ws = sh.sheet1

	rows = ws.get_all_values()
	if not rows:
		_cache.update({"products": [], "last_update": now})
		return []

	headers_raw = rows[0]
	headers = [HEADER_ALIASES.get(_norm(h), _norm(h)) for h in headers_raw]

	products = []
	for r in rows[1:]:
		if not any(r):
			continue
		item = {}
		for i, val in enumerate(r):
			if i >= len(headers):
				continue
			k = headers[i]
			v = (val or "").strip()

			# обработка цены (+15%)
			if k == "цена" and v:
				digits = re.sub(r"[^\d]", "", v)
				if digits:
					try:
						num = int(digits)
						num = int(num * 1.15)
						v = f"{num:,} ₽".replace(",", " ")
					except Exception:
						pass

			item[k] = v

		if item.get("название"):
			item["категория"] = item.get("категория") or "Прочее"
			products.append(item)

	_cache["products"] = products
	_cache["last_update"] = now
	return products
