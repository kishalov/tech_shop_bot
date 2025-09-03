from aiogram import Router, types, F
from aiogram.filters import Command
from keyboards import main_kb
from handlers_catalog import show_categories, user_cart  # импорт корзины

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Это бот Sterodium.\n"
        "Используй меню ниже для навигации:",
        reply_markup=main_kb
    )

# @router.message(Command("help"))
# @router.message(F.text == "ℹ️ Помощь")
# async def cmd_help(message: types.Message):
#     await message.answer(
#         "ℹ️ Доступные команды:\n"
#         "📂 Каталог — открыть список категорий\n"
#         "🛒 Корзина — посмотреть корзину\n"
#         "ℹ️ Помощь — показать справку"
#     )

@router.message(F.text == "📂 Каталог")
async def open_catalog(message: types.Message):
    await show_categories(message)

@router.message(F.text == "🛒 Корзина")
async def open_cart(message: types.Message):
    user_id = message.from_user.id
    cart = user_cart.get(user_id, [])

    if not cart:
        await message.answer("🛒 Ваша корзина пока пуста.")
        return

    # список товаров (только названия)
    text = "🛒 Ваша корзина:\n\n"
    for idx, p in enumerate(cart, start=1):
        text += f"{idx}. {p['название']}\n"

    # кнопка заказать
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Заказать", url="https://t.me/olegobydenov")]
        ]
    )

    await message.answer(text, reply_markup=kb)
