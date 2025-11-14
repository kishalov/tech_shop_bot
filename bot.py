# bot.py
import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers.handlers import router as base_router
from channel_store import ensure_refreshed
from sync_channel import client as telethon_client   # ← добавили

REFRESH_INTERVAL = 3600

async def refresh_channel_job():
	while True:
		try:
			ensure_refreshed(force=True)
			print("🔄 Канал синхронизирован.")
		except Exception as e:
			print(f"⚠ Ошибка синхронизации: {e}")
		await asyncio.sleep(REFRESH_INTERVAL)

async def main():
	# ←←← ВАЖНО: запускаем Telethon перед ботом
	await telethon_client.start()
	print("⚡ Telethon подключён")

	bot = Bot(token=BOT_TOKEN)
	dp = Dispatcher()

	dp.include_router(base_router)

	asyncio.create_task(refresh_channel_job())

	print("🤖 Бот запущен.")
	await dp.start_polling(bot)

if __name__ == "__main__":
	asyncio.run(main())
