import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router as base_router
from handlers_catalog import router as catalog_router

async def refresh_catalog_job():
	while True:
		from sheets import get_products
		get_products(ttl=0)  # сбрасываем кэш
		print("🔄 Каталог обновлён из таблицы.")
		await asyncio.sleep(3600)  # раз в час

async def main():
	bot = Bot(token=BOT_TOKEN)
	dp = Dispatcher()

	dp.include_router(base_router)
	dp.include_router(catalog_router)

	# запускаем обновление каталога в фоне
	asyncio.create_task(refresh_catalog_job())

	await dp.start_polling(bot)
