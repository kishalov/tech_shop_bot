import os
import gspread
import time
import re

# --- универсальный путь до creds.json ---
server_path = "/configs/creds.json"  # для хостинга (Linux)
local_path = os.path.join(os.path.dirname(__file__), "configs", "creds.json")

# выбираем путь, который существует
creds_path = server_path if os.path.exists(server_path) else local_path

gc = gspread.service_account(filename=creds_path)

# Кэш (5 минут по умолчанию)
_cache = {"products": [], "last_update": 0}

# Нормализация заголовков: "Название товара" -> "название", "IMAGE url" -> "фото", и т.п.
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

    "description": "описание",
    "описание": "описание",
    "характеристики": "описание",

    "brand": "бренд",
    "бренд": "бренд",
    "lab": "бренд",

    "qty": "кол-во",
    "quantity": "кол-во",
    "кол-во": "кол-во",

    "strength": "сила",
    "сила": "сила",

    # изображения
    "image": "фото",
    "images": "фото",
    "photo": "фото",
    "picture": "фото",
    "img": "фото",
    "фото": "фото",
    "изображение": "фото",
    
    "subcategory": "подкатегория",
    "sub-category": "подкатегория",
    "подкатегория": "подкатегория",
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def convert_drive_link(link: str) -> str:
    """Google Drive /file/d/<id>/view -> прямой uc?export=download&id=<id>"""
    link = (link or "").strip()
    if "drive.google.com/file/d/" in link:
        try:
            file_id = link.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        except Exception:
            return ""
    return link

def _first_url(cell: str) -> str:
    """Берём из ячейки первый URL (разделители: пробел, запятая, перенос строки)."""
    raw = (cell or "").replace(",", " ")
    parts = [p for p in raw.split() if p.startswith("http")]
    return parts[0] if parts else ""

def get_products(
    sheet_name: str = "Catalog",
    worksheet_name: str | None = None,
    ttl: int = 300,  # 5 минут
) -> list[dict]:
    """Читает гугл-таблицу динамически по заголовкам и возвращает список словарей."""
    now = time.time()
    if _cache["products"] and now - _cache["last_update"] <= ttl:
        return _cache["products"]

    sh = gc.open(sheet_name)
    ws = sh.worksheet(worksheet_name) if worksheet_name else sh.sheet1

    rows = ws.get_all_values()  # без типов, но нам ок
    if not rows:
        _cache.update({"products": [], "last_update": now})
        return []

    # заголовки
    headers_raw = rows[0]
    headers = []
    for h in headers_raw:
        key = _norm(h)
        key = HEADER_ALIASES.get(key, key)  # маппим к нашим каноническим
        headers.append(key)

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

            if not k:
                continue

            if k == "фото":
                v = convert_drive_link(_first_url(v))

             # ---- вот сюда добавим обработку цены ----
            if k == "цена" and v:
                import re
                digits = re.sub(r"[^\d]", "", v)  # убрали всё кроме цифр
                if digits:
                    try:
                        num = int(digits)
                        num = int(num * 1.15)  # прибавили 15%
                        v = f"{num:,} ₽".replace(",", " ")
                    except Exception:
                        pass

            item[k] = v

        if item.get("название"):
            # категория по умолчанию
            item["категория"] = item.get("категория") or "Прочее"
            products.append(item)

    _cache["products"] = products
    _cache["last_update"] = now
    return products
