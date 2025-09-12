# keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📂 Меню")],
        [KeyboardButton(text="🛒 Корзина"), KeyboardButton(text="ℹ️ Помощь")],
    ],
    resize_keyboard=True
)
