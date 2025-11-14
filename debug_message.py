from telethon import TelegramClient
import os
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
source_channel = os.getenv("SOURCE_CHANNEL")

client = TelegramClient("debug_session", api_id, api_hash)

async def code_callback():
    return input("Enter the code you received: ")

async def main():
    # ЯВНО указываем, что Telethon должен ЗАПРОСИТЬ ХЭШ
    await client.start(
        phone=input("Enter your phone: "),
        code_callback=code_callback
    )

    print("Connected!")

    async for msg in client.iter_messages(source_channel, limit=20):
        print("ID:", msg.id)
        print("has reply_markup:", bool(msg.reply_markup))

        if msg.reply_markup:
            print("reply_markup:", msg.reply_markup.to_dict())

        print("-" * 50)

client.loop.run_until_complete(main())
