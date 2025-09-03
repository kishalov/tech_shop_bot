import gspread
import time

gc = gspread.service_account(filename="creds.json")

# Кэш: хранит список продуктов и время последнего обновления
_cache = {"products": [], "last_update": 0}

def convert_drive_link(link: str) -> str:
    """Преобразует ссылку Google Drive в прямую для скачивания"""
    if "drive.google.com/file/d/" in link:
        try:
            file_id = link.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        except:
            return ""
    return link

def get_products(
    sheet_name: str = "SterodiumCatalog",
    worksheet_name: str = "Anabolic Warehouse Pricelist",
    ttl: int = 300  # время жизни кэша в секундах (по умолчанию 5 минут)
):
    """Загружает продукты из Google Sheets с кэшированием"""
    now = time.time()

    # если кэш устарел — обновляем
    if now - _cache["last_update"] > ttl or not _cache["products"]:
        sh = gc.open(sheet_name)
        worksheet = sh.worksheet(worksheet_name)
        records = worksheet.get_all_records()

        products = []
        for row in records:
            if not any(row.values()):
                continue

            photo_raw = str(row.get("IMAGE", "")).strip()
            # берём только первую ссылку
            photo = ""
            if photo_raw:
                first_link = photo_raw.replace(",", " ").split()[0]
                photo = convert_drive_link(first_link)

            product = {
                "название": str(row.get("PRODUCT", "")).strip(),
                "кол-во": str(row.get("QUANTITY", "")).strip(),
                "сила": str(row.get("STRENGTH", "")).strip(),
                "описание": str(row.get("DESCRIPTION", "")).strip(),
                "цена": str(row.get("WholeSale", "")).strip(),
                "бренд": str(row.get("LAB", "")).strip(),
                "категория": str(row.get("CATEGORY", "")).strip(),
                "тип": str(row.get("TYPE", "")).strip(),
                "фото": photo,  # только одно фото
            }

            if product["название"]:
                products.append(product)

        # обновляем кэш
        _cache["products"] = products
        _cache["last_update"] = now

    return _cache["products"]
