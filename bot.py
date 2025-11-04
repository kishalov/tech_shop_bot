import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router as base_router
from handlers_catalog import router as catalog_router
from sheets import get_products


REFRESH_INTERVAL = 3600  # каждые 60 минут


async def refresh_catalog_job():
	"""
	Фоновая задача: периодически обновляет кэш каталога из Google Sheets.
	"""
	while True:
		try:
			get_products(ttl=0)  # сбрасываем кэш и перезагружаем товары
			print("🔄 Каталог обновлён из таблицы.")
		except Exception as e:
			print(f"⚠️ Ошибка при обновлении каталога: {e}")
		await asyncio.sleep(REFRESH_INTERVAL)


async def main():
	bot = Bot(token=BOT_TOKEN)
	dp = Dispatcher()

	# подключаем роутеры
	dp.include_router(base_router)
	dp.include_router(catalog_router)

	# запускаем фоновое обновление
	asyncio.create_task(refresh_catalog_job())

	print("🤖 Бот запущен и ждёт обновлений каталога.")
	await dp.start_polling(bot)


if __name__ == "__main__":
	asyncio.run(main())
