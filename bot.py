import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router as base_router
from handlers_catalog import router as catalog_router

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # подключаем роутеры
    dp.include_router(base_router)
    dp.include_router(catalog_router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
