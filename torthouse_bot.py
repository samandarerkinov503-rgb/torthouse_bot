import os
import json

import logging
import asyncio
import time
import uuid
from datetime import datetime
from dotenv import load_dotenv
import pytz
import aiohttp
import aiofiles
import phonenumbers
import aiosqlite
import re

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- Konfiguratsiya va logging ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
ORDER_CHANNEL_ID = os.getenv("ORDER_CHANNEL_ID")
if ORDER_CHANNEL_ID:
    try:
        ORDER_CHANNEL_ID = int(ORDER_CHANNEL_ID)
    except ValueError:
        raise ValueError("ORDER_CHANNEL_ID noto‘g‘ri formatda. .env faylida to‘g‘ri raqamli ID kiriting.")
else:
    ORDER_CHANNEL_ID = None

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. .env ga qo'ying.")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS topilmadi yoki noto‘g‘ri formatda. .env ga to‘g‘ri ID kiriting.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB_FILE = "bot.db"

# --- Mahsulotlar va filiallar ---
PRODUCTS = [
    {"id": "p1", "name_uz": "Shokoladli tort", "name_ru": "Шоколадный торт", "price": 120000,
     "photo": "https://i.imgur.com/5z3X0aS.jpg"},  # Haqiqiy shokoladli tort rasmi
    {"id": "p2", "name_uz": "Muzqaymoqli pirojnye", "name_ru": "Пирожное с мороженым", "price": 25000,
     "photo": "https://i.imgur.com/8y6v7Xj.jpg"},  # Haqiqiy pirojnye rasmi
    {"id": "p3", "name_uz": "Keks", "name_ru": "Кекс", "price": 8000,
     "photo": "https://i.imgur.com/4k9p2Lm.jpg"},  # Haqiqiy keks rasmi
]

BRANCHES = [
    {"id": "b_yangiq", "name_uz": "Yangiqurgon filiali", "name_ru": "Филиал Янгикургон",
     "address": "Yangiqurgon manzili", "lat": 41.0, "lon": 71.0, "map": "https://maps.google.com/?q=41,71"},
    {"id": "b_uychi", "name_uz": "Uychi filiali", "name_ru": "Филиал Уччи",
     "address": "Uychi manzili", "lat": 41.1, "lon": 71.1, "map": "https://maps.google.com/?q=41.1,71.1"},
    {"id": "b_chortoq", "name_uz": "Chortoq markaziy filiali", "name_ru": "Чартак центральный филиал",
     "address": "Chortoq manzili", "lat": 41.2, "lon": 71.2, "map": "https://maps.google.com/?q=41.2,71.2"},
    {"id": "b_namangan", "name_uz": "Namangan bo‘yicha", "name_ru": "По Намангану",
     "address": "Namangan manzili", "lat": 41.3, "lon": 71.3, "map": "https://maps.google.com/?q=41.3,71.3"},
]

# --- Xabarlar (uz/ru) ---
MSG = {
    "choose_lang": {"uz": "🌐 Tilni tanlang:", "ru": "🌐 Выберите язык:"},
    "main_menu_title": {"uz": "🏠 Asosiy menyu", "ru": "🏠 Главное меню"},
    "menu_products": {"uz": "🛍 Mahsulotlar va buyurtma berish", "ru": "🛍 Товары и заказ"},
    "menu_branches": {"uz": "🏬 Filiallarimiz", "ru": "🏬 Наши филиалы"},
    "menu_cart": {"uz": "🛒 Savat", "ru": "🛒 Корзина"},
    "menu_orders": {"uz": "📦 Buyurtmalarim", "ru": "📦 Мои заказы"},
    "menu_help": {"uz": "📞 Yordam (admin bilan bog‘lanish)", "ru": "📞 Помощь (связь с админом)"},
    "back": {"uz": "🔙 Orqaga", "ru": "🔙 Назад"},
    "menu": {"uz": "🏠 Asosiy menyuga", "ru": "🏠 В главное меню"},
    "ask_custom": {"uz": "📝 Buyurtma tafsilotlarini kiriting (rasm yuborishingiz mumkin):", "ru": "📝 Введите детали заказа (можно отправить фото):"},
    "ask_contact": {"uz": "📞 Iltimos, telefon raqamingizni yuboring:", "ru": "📞 Пожалуйста, отправьте ваш номер телефона:"},
    "invalid_phone": {"uz": "❌ Noto‘g‘ri telefon raqami. Iltimos, to‘g‘ri raqam kiriting (masalan, +998901234567).", "ru": "❌ Неверный номер телефона. Пожалуйста, введите корректный номер (например, +998901234567)."},
    "ask_address": {"uz": "📍 Iltimos, manzilingizni yuboring:", "ru": "📍 Пожалуйста, отправьте адрес:"},
    "ask_name": {"uz": "👤 Ism va familiyangizni yuboring:", "ru": "👤 Отправьте имя и фамилию:"},
    "order_sent": {"uz": "✅ Buyurtmangiz qabul qilindi! Tez orada adminlar siz bilan bog'lanadi.", "ru": "✅ Ваш заказ принят! Мы свяжемся с вами в ближайшее время."},
    "cart_empty": {"uz": "🛒 Savat bo'sh. Iltimos, mahsulot qo'shing.", "ru": "🛒 Корзина пуста. Пожалуйста, добавьте товары."},
    "no_orders": {"uz": "📋 Buyurtmalar topilmadi", "ru": "📋 Заказы не найдены"},
    "not_admin": {"uz": "🚫 Siz admin emassiz.", "ru": "🚫 Вы не администратор."},
    "confirm_added": {"uz": "✅ Mahsulot savatga qo'shildi.", "ru": "✅ Товар добавлен в корзину."},
    "removed": {"uz": "✅ O‘chirildi.", "ru": "✅ Удалено."},
    "choose_delivery": {"uz": "🚚 Yetkazib berish turini tanlang:", "ru": "🚚 Выберите тип доставки:"},
    "invalid_image": {"uz": "❌ Rasm yuborishda xato. Iltimos, boshqa rasm yuboring.", "ru": "❌ Ошибка при отправке изображения. Пожалуйста, отправьте другое изображение."},
    "location_error": {"uz": "❌ Lokatsiya qabul qilishda xato. Iltimos, qayta yuboring.", "ru": "❌ Ошибка при получении локации. Пожалуйста, отправьте заново."},
    "cart_too_large": {"uz": "🛒 Savat juda katta. Iltimos, ba'zi mahsulotlarni o'chiring va qaytadan urinib ko'ring.", "ru": "🛒 Корзина слишком большая. Пожалуйста, удалите некоторые товары и попробуйте снова."},
    "invalid_input": {"uz": "❌ Noto‘g‘ri ma'lumot kiritildi. Iltimos, qayta urinib ko‘ring.", "ru": "❌ Введены неверные данные. Пожалуйста, попробуйте снова."},
    "order_confirm": {"uz": "✅ Buyurtma tasdiqlandi. Batafsil: {details}", "ru": "✅ Заказ подтвержден. Подробности: {details}"},
    "missing_pickup_info": {"uz": "❌ Ism yoki telefon raqami kiritilmagan. Iltimos, qayta kiriting.", "ru": "❌ Имя или номер телефона не указаны. Пожалуйста, введите заново."}
}

STATUS_MAP = {
    "received": {"uz": "✅ Qabul qilindi", "ru": "✅ Принят"},
    "preparing": {"uz": "⏳ Tayyorlanmoqda", "ru": "⏳ Готовится"},
    "delivered": {"uz": "🚚 Yetkazib berildi", "ru": "🚚 Доставлен"}
}

def get_msg(key, lang, **kwargs):
    template = MSG[key][lang]
    return template.format(**kwargs)

class UserStates(StatesGroup):
    awaiting_custom_text = State()
    awaiting_custom_photo = State()
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_address = State()
    awaiting_location = State()
    awaiting_pickup_name = State()
    awaiting_pickup_phone = State()
    awaiting_pickup_branch = State()

# --- Ma'lumotlarni tozalash funksiyasi ---
def sanitize_input(text):
    if not text:
        return ""
    # Faqat harflar, raqamlar va ba'zi maxsus belgilar qoladi, uzunlik 100 belgiga cheklanadi
    return re.sub(r'[^\w\s@+.,-]', '', text.strip()[:100])

# --- Ma'lumotlar bazasi funksiyalari ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                lang TEXT,
                name TEXT,
                phone TEXT,
                address TEXT,
                selected_branch TEXT,
                orders TEXT DEFAULT '[]'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS carts (
                user_id TEXT PRIMARY KEY,
                cart_data TEXT DEFAULT '{}'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id TEXT,
                order_data TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS order_counter (
                counter INTEGER DEFAULT 0
            )
        """)
        await db.execute("INSERT OR IGNORE INTO order_counter (counter) VALUES (0)")
        await db.commit()
        logging.info("DB initsializatsiya qilindi.")

async def get_next_order_number():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT counter FROM order_counter")
        counter = (await cursor.fetchone())[0]
        new_counter = counter + 1
        await db.execute("UPDATE order_counter SET counter = ?", (new_counter,))
        await db.commit()
        return f"#{str(new_counter).zfill(3)}"

async def load_user(user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row:
            return {
                "lang": row[1],
                "name": row[2],
                "phone": row[3],
                "address": row[4],
                "selected_branch": row[5],
                "orders": json.loads(row[6])
            }
        return {}

async def save_user(user_id, data):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, lang, name, phone, address, selected_branch, orders) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, data.get("lang"), sanitize_input(data.get("name")), sanitize_input(data.get("phone")),
             sanitize_input(data.get("address")), data.get("selected_branch"), json.dumps(data.get("orders", [])))
        )
        await db.commit()

async def load_cart(user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT cart_data FROM carts WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return {}

async def save_cart(user_id, cart):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO carts (user_id, cart_data) VALUES (?, ?)",
            (user_id, json.dumps(cart))
        )
        await db.commit()

async def load_orders():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT order_data FROM orders")
        rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

async def save_order(order):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO orders (order_id, user_id, order_data) VALUES (?, ?, ?)",
            (order["id"], order["user_id"], json.dumps(order))
        )
        await db.commit()

async def update_order(order_id, updated_order):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE orders SET order_data = ? WHERE order_id = ?",
            (json.dumps(updated_order), order_id)
        )
        await db.commit()

async def load_user_orders(user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT order_data FROM orders WHERE user_id = ?", (user_id,))
        rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

async def notify_admins(message):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message)
        except Exception as e:
            logging.error(f"Adminga xabar yuborishda xato: {e}")

def get_current_time():
    tz = pytz.timezone("Asia/Tashkent")
    return datetime.now(tz).isoformat()

def get_product(pid):
    for p in PRODUCTS:
        if p["id"] == pid:
            return p
    return None

def get_branch(bid):
    for b in BRANCHES:
        if b["id"] == bid:
            return b
    return None

def fmt_price(n):
    return f"{n:,}".replace(",", " ")

async def validate_image_url(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return False
                content_type = resp.headers.get("Content-Type", "").lower()
                return content_type in ["image/jpeg", "image/png", "image/gif"]
    except Exception as e:
        logging.error(f"Rasm URL tekshirishda xato ({url}): {e}")
        return False

def validate_phone(phone):
    try:
        parsed = phonenumbers.parse(phone, None)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.phonenumberutil.NumberParseException:
        return False

def format_item(item, lang, include_price=True):
    if item["type"] == "product":
        name = item["name_uz"] if lang == "uz" else item["name_ru"]
        qty = item.get("qty", 1)
        price = item.get("price", 0) * qty if include_price else None
        price_text = f" — {fmt_price(price)} so'm" if include_price else ""
        return f"📦 {name} x{qty}{price_text}"
    else:
        desc = sanitize_input(item.get("desc", ""))[:50]
        qty = item.get("qty", 1)
        return f"🎂 Maxsus: {desc}... x{qty} (narx admin bilan aniqlanadi)" if lang == "uz" else f"🎂 Индивидуал: {desc}... x{qty} (цена уточняется админом)"

def format_cart(cart, lang):
    lines = [format_item(item, lang) for item in cart.values()]
    total = sum(item.get("price", 0) * item.get("qty", 1) for item in cart.values() if item["type"] == "product")
    lines.append(f"💰 Jami: {fmt_price(total)} so'm" if lang == "uz" else f"💰 Итого: {fmt_price(total)}")
    result = "\n".join(lines)
    if len(result) > 4000:
        return MSG["cart_too_large"][lang]
    return result

def format_order_details(order, lang):
    b = get_branch(order.get("branch"))
    lines = []
    lines.append(f"🆔 Buyurtma ID: {order['id']}")
    lines.append(f"👤 Foydalanuvchi: {sanitize_input(order.get('user_name'))} ({order.get('user_id')})")
    lines.append(f"📞 Telefon: {sanitize_input(order.get('phone'))}")
    lines.append(f"🚚 Yetkazib berish turi: {order.get('delivery_type').capitalize()}")
    if order.get("address"):
        lines.append(f"🏠 Manzil: {sanitize_input(order.get('address'))}")
    if order.get("location"):
        loc = order["location"]
        lines.append(f"📍 Lokatsiya: https://maps.google.com/?q={loc['lat']},{loc['lon']}")
    lines.append("📋 Buyurtma tarkibi:")
    for item in order["items"].values():
        lines.append(f" - {format_item(item, lang)}")
    if b:
        lines.append(f"🏬 Filial: {b['name_uz'] if lang == 'uz' else b['name_ru']}")
        lines.append(f"🗺 Xaritasi: {b['map']}")
    lines.append(f"📊 Holat: {STATUS_MAP.get(order.get('status'), {'uz': 'N/A', 'ru': 'N/A'})[lang]}")
    lines.append(f"🕒 Yaratilgan vaqt: {order.get('created_at')}")
    return "\n".join(lines)

# --- Klaviaturalar ---
def create_inline_kb(buttons, include_back_menu=True, lang="uz"):
    rows = []
    for row in buttons:
        row_buttons = []
        for text, data in row:
            row_buttons.append(InlineKeyboardButton(text=text, callback_data=data))
        rows.append(row_buttons)
    if include_back_menu:
        rows.append([InlineKeyboardButton(text=MSG["back"][lang], callback_data="back")])
        rows.append([InlineKeyboardButton(text=MSG["menu"][lang], callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")]
    ])

def main_menu_kb(lang):
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="🛍 " + MSG["menu_products"][lang])],
        [KeyboardButton(text="🏬 " + MSG["menu_branches"][lang])],
        [KeyboardButton(text="🛒 " + MSG["menu_cart"][lang])],
        [KeyboardButton(text="📦 " + MSG["menu_orders"][lang])],
        [KeyboardButton(text="📞 " + MSG["menu_help"][lang])]
    ])

def remove_keyboard():
    return ReplyKeyboardRemove()

async def send_menu_response(context, text, reply_markup, delete_previous=False):
    if delete_previous:
        try:
            await context.message.delete()
        except:
            pass
    if isinstance(context, CallbackQuery):
        await context.message.answer(text, reply_markup=reply_markup)
    else:
        await context.answer(text, reply_markup=reply_markup)

# --- /start: til tanlash, so'ng asosiy menyu ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    user = await load_user(user_id)
    if not user:
        user = {"lang": None, "orders": []}
        await save_user(user_id, user)
    await message.answer(MSG["choose_lang"]["uz"] + "\n" + MSG["choose_lang"]["ru"], reply_markup=lang_kb())

@router.callback_query(lambda c: c.data and c.data.startswith("lang_"))
async def on_lang(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split("_", 1)[1]
    user_id = str(cb.from_user.id)
    user = await load_user(user_id)
    user["lang"] = lang
    await save_user(user_id, user)
    await state.clear()
    await cb.answer()
    await send_menu_response(cb, MSG["main_menu_title"][lang], main_menu_kb(lang), delete_previous=True)

# --- Asosiy menyu handlerlari ---
@router.message(lambda m: m.text and m.text in ["🏠 Asosiy menyuga", "🏠 В главное меню"])
async def menu_text(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.clear()
    await message.answer(MSG["main_menu_title"][lang], reply_markup=main_menu_kb(lang))

@router.callback_query(lambda c: c.data == "menu")
async def menu_cb(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.clear()
    await cb.answer()
    await send_menu_response(cb, MSG["main_menu_title"][lang], main_menu_kb(lang), delete_previous=True)

@router.callback_query(lambda c: c.data == "back")
async def back_cb(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await state.clear()
    await send_menu_response(cb, MSG["main_menu_title"][lang], main_menu_kb(lang), delete_previous=True)

# --- Menu: Filiallarimiz ---
@router.message(lambda m: m.text and m.text.startswith("🏬 "))
async def menu_branches_text(message: Message):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await menu_branches_common(message, user_id, lang)

@router.callback_query(lambda c: c.data == "menu_branches")
async def menu_branches_cb(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await menu_branches_common(cb, user_id, lang)

async def menu_branches_common(context, user_id, lang):
    text_lines = [f"🏬 {MSG['menu_branches'][lang]}:"]
    for b in BRANCHES:
        name = b['name_uz'] if lang == 'uz' else b['name_ru']
        text_lines.append(f"📍 {name}\n🏠 {b['address']}\n🗺 Map: {b['map']}\n")
    await send_menu_response(context, "\n".join(text_lines), create_inline_kb([], lang=lang), delete_previous=True)

# --- Menu: Yordam (admin bilan bog'lanish) ---
@router.message(lambda m: m.text and m.text.startswith("📞 "))
async def menu_help_text(message: Message):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await menu_help_common(message, user_id, lang)

@router.callback_query(lambda c: c.data == "menu_help")
async def menu_help_cb(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await menu_help_common(cb, user_id, lang)

async def menu_help_common(context, user_id, lang):
    admin_phone = "+998500972027"
    admin_telegram = "@samandarerkinov_IT"
    text = f"📞 {admin_phone}\n👤 {admin_telegram}"
    await send_menu_response(context, text, create_inline_kb([], lang=lang), delete_previous=True)

# --- Menu: Mahsulotlar va buyurtma berish -> filial tanlash ---
@router.message(lambda m: m.text and m.text.startswith("🛍 "))
async def menu_products_text(message: Message):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await menu_products_common(message, user_id, lang)

@router.callback_query(lambda c: c.data == "menu_products")
async def menu_products_cb(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await menu_products_common(cb, user_id, lang)

async def menu_products_common(context, user_id, lang):
    buttons = [[(b['name_uz'] if lang=='uz' else b['name_ru'], f"select_branch_{b['id']}")] for b in BRANCHES]
    kb = create_inline_kb(buttons, lang=lang)
    await send_menu_response(context, ("🏬 Filialni tanlang:" if lang == 'uz' else "🏬 Выберите филиал:"), kb, delete_previous=True)

@router.callback_query(lambda c: c.data and c.data.startswith("select_branch_"))
async def select_branch(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    branch_id = cb.data.split("_", 2)[2]
    user = await load_user(user_id)
    user["selected_branch"] = branch_id
    await save_user(user_id, user)
    lang = user.get("lang", "uz")
    await state.clear()
    await cb.answer((f"✅ {get_branch(branch_id)['name_uz']} tanlandi" if lang == 'uz' else f"✅ {get_branch(branch_id)['name_ru']} выбрана"))
    buttons = [
        [("🍰 Tayyor shirinliklar" if lang=='uz' else "🍰 Наши сладости", "show_products")],
        [("🎂 Maxsus buyurtma" if lang=='uz' else "🎂 Индивидуальный заказ", "start_custom")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await send_menu_response(cb, (f"🏬 Filial: {get_branch(branch_id)['name_uz']}" if lang=='uz' else f"🏬 Филиал: {get_branch(branch_id)['name_ru']}"), kb, delete_previous=True)

# --- Tayyor mahsulotlar ---
@router.callback_query(lambda c: c.data == "show_products")
async def show_products(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    text = ("🍰 Tayyor shirinliklar:" if lang == 'uz' else "🍰 Наши готовые сладости:")
    await send_menu_response(cb, text, create_inline_kb([], lang=lang), delete_previous=True)
    for p in PRODUCTS:
        name = p['name_uz'] if lang=='uz' else p['name_ru']
        caption = f"🍰 {name}\n💰 Narx: {fmt_price(p['price'])} so'm" if lang == 'uz' else f"🍰 {name}\n💰 Цена: {fmt_price(p['price'])}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Savatga qo'shish", callback_data=f"view_{p['id']}")],
        ])
        if p.get("photo") and await validate_image_url(p["photo"]):
            try:
                await bot.send_photo(cb.from_user.id, photo=p["photo"], caption=caption, reply_markup=kb)
            except Exception as e:
                logging.error(f"Rasm yuborishda xato (product {p['id']}): {e}")
                await cb.message.answer(caption, reply_markup=kb)
        else:
            await cb.message.answer(caption, reply_markup=kb)

@router.callback_query(lambda c: c.data and c.data.startswith("view_"))
async def view_product(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    pid = cb.data.split("_",1)[1]
    p = get_product(pid)
    if not p:
        await cb.answer("Mahsulot topilmadi")
        return
    lang = (await load_user(user_id)).get("lang", "uz")
    caption = f"🍰 {p['name_uz'] if lang=='uz' else p['name_ru']}\n💰 Narx: {fmt_price(p['price'])} so'm" if lang=='uz' else f"🍰 {p['name_ru']}\n💰 Цена: {fmt_price(p['price'])}"
    await state.update_data(temp_sel={"pid": pid, "qty": 1})
    kb = create_inline_kb([
        [("1", f"setqty_{pid}_1"), ("2", f"setqty_{pid}_2"), ("3", f"setqty_{pid}_3"), ("4", f"setqty_{pid}_4"), ("5", f"setqty_{pid}_5")],
        [(MSG["menu_cart"][lang], f"addcart_{pid}")]
    ], lang=lang)
    if p.get("photo") and await validate_image_url(p["photo"]):
        try:
            await bot.send_photo(cb.from_user.id, photo=p["photo"], caption=caption, reply_markup=kb)
        except Exception as e:
            logging.error(f"Rasm yuborishda xato (product {p['id']}): {e}")
            await cb.message.answer(caption, reply_markup=kb)
    else:
        await cb.message.answer(caption, reply_markup=kb)
    await cb.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("setqty_"))
async def set_quantity(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    parts = cb.data.split("_")
    pid = parts[1]
    qty = int(parts[2])
    await state.update_data(temp_sel={"pid": pid, "qty": qty})
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer((f"✅ Tanlandi: {qty} dona" if lang=='uz' else f"✅ Выбрано: {qty} шт."))

@router.callback_query(lambda c: c.data and c.data.startswith("addcart_"))
async def add_to_cart_cb(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    pid = cb.data.split("_",1)[1]
    data = await state.get_data()
    qty = data.get("temp_sel", {}).get("qty", 1)
    p = get_product(pid)
    if not p:
        await cb.answer("Mahsulot topilmadi")
        return
    cart = await load_cart(user_id)
    if pid in cart:
        cart[pid]["qty"] += qty
    else:
        cart[pid] = {"type":"product", "pid": pid, "name_uz": p["name_uz"], "name_ru": p["name_ru"],
                     "price": p["price"], "qty": qty}
    await save_cart(user_id, cart)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer(MSG["confirm_added"][lang])
    buttons = [
        [(MSG["menu_cart"][lang], "menu_cart")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await send_menu_response(cb, MSG["confirm_added"][lang], kb, delete_previous=True)

# --- Maxsus buyurtma oqimi ---
@router.callback_query(lambda c: c.data == "start_custom")
async def start_custom(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.set_state(UserStates.awaiting_custom_text)
    await cb.answer()
    await send_menu_response(cb, MSG["ask_custom"][lang], remove_keyboard(), delete_previous=True)

@router.message(UserStates.awaiting_custom_text)
async def handle_custom_text(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    text = sanitize_input(message.text or "")
    if not text:
        lang = (await load_user(user_id)).get("lang", "uz")
        await message.answer(MSG["invalid_input"][lang])
        return
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.update_data(custom_text=text)
    await state.set_state(UserStates.awaiting_custom_photo)
    buttons = [
        [("📸 Rasm yuborish" if lang=='uz' else "📸 Отправить фото", "custom_send_photo")],
        [("❌ Rasm shart emas / Skip" if lang=='uz' else "❌ Пропустить фото", "custom_skip_photo")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await message.answer(("📸 Rasm yuboring yoki 'Skip' bosing." if lang=='uz' else "📸 Отправьте фото или нажмите 'Пропустить'."), reply_markup=kb)

@router.callback_query(lambda c: c.data == "custom_send_photo", UserStates.awaiting_custom_photo)
async def custom_send_photo_cb(cb: CallbackQuery, state: FSMContext):
    lang = (await load_user(str(cb.from_user.id))).get("lang", "uz")
    await cb.answer()
    await send_menu_response(cb, ("📸 Iltimos, rasm yuboring:" if lang=='uz' else "📸 Пожалуйста, отправьте фото:"), None, delete_previous=True)

@router.callback_query(lambda c: c.data == "custom_skip_photo", UserStates.awaiting_custom_photo)
async def custom_skip_photo_cb(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    data = await state.get_data()
    desc = data.get("custom_text", "")
    key = f"custom_{int(time.time())}"
    cart = await load_cart(user_id)
    cart[key] = {
        "type": "custom",
        "desc": desc,
        "photo": None,
        "qty": 1
    }
    await save_cart(user_id, cart)
    await state.clear()
    await cb.answer(("✅ Maxsus buyurtma savatga qo'shildi." if lang=='uz' else "✅ Индивидуальный заказ добавлен в корзину."))
    buttons = [
        [(MSG["menu_cart"][lang], "menu_cart")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await send_menu_response(cb, MSG["confirm_added"][lang], kb, delete_previous=True)

@router.message(F.photo, UserStates.awaiting_custom_photo)
async def handle_custom_photo(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    desc = data.get("custom_text", "")
    key = f"custom_{int(time.time())}"
    cart = await load_cart(user_id)
    cart[key] = {
        "type": "custom",
        "desc": desc,
        "photo": file_id,
        "qty": 1
    }
    await save_cart(user_id, cart)
    await state.clear()
    await message.answer(("✅ Rasm qabul qilindi va buyurtma savatga qo'shildi." if lang=='uz' else "✅ Фото принято и заказ добавлен в корзину."))
    buttons = [
        [(MSG["menu_cart"][lang], "menu_cart")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await message.answer(MSG["confirm_added"][lang], reply_markup=kb)

# --- Savatni ko'rsatish va boshqarish ---
async def show_cart(context, user_id, lang, delete_previous=False):
    cart = await load_cart(user_id)
    if not cart:
        await send_menu_response(context, MSG["cart_empty"][lang], create_inline_kb([], lang=lang), delete_previous)
        return
    text = format_cart(cart, lang)
    buttons = []
    for key, item in cart.items():
        label = (item.get("name_uz") if lang=='uz' else item.get("name_ru")) if item["type"]=="product" else ("Maxsus" if lang=='uz' else "Индивидуал")
        buttons.append([("➖ " + label, f"dec_{key}"), ("⛔ " + label, f"rem_{key}")])
    buttons.append([("🗑 Savatni tozalash" if lang=='uz' else "🗑 Очистить корзину", "clear_cart")])
    buttons.append([("📝 Buyurtma berish" if lang=='uz' else "📝 Оформить заказ", "checkout")])
    kb = create_inline_kb(buttons, include_back_menu=False, lang=lang)
    await send_menu_response(context, text, kb, delete_previous)

@router.message(lambda m: m.text and m.text.startswith("🛒 "))
async def show_cart_text(message: Message):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await show_cart(message, user_id, lang)

@router.callback_query(lambda c: c.data == "menu_cart" or c.data == "show_cart")
async def show_cart_cb(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await show_cart(cb, user_id, lang, delete_previous=True)

@router.callback_query(lambda c: c.data and c.data.startswith("dec_"))
async def dec_item(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    key = cb.data.split("_",1)[1]
    cart = await load_cart(user_id)
    lang = (await load_user(user_id)).get("lang", "uz")
    if key in cart:
        cart[key]["qty"] -= 1
        if cart[key]["qty"] <= 0:
            del cart[key]
        await save_cart(user_id, cart)
        await cb.answer(MSG["removed"][lang])
    else:
        await cb.answer("Element topilmadi")
    await show_cart(cb, user_id, lang, delete_previous=True)

@router.callback_query(lambda c: c.data and c.data.startswith("rem_"))
async def rem_item(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    key = cb.data.split("_",1)[1]
    cart = await load_cart(user_id)
    lang = (await load_user(user_id)).get("lang", "uz")
    if key in cart:
        del cart[key]
        await save_cart(user_id, cart)
        await cb.answer(MSG["removed"][lang])
    else:
        await cb.answer("Element topilmadi")
    await show_cart(cb, user_id, lang, delete_previous=True)

@router.callback_query(lambda c: c.data == "clear_cart")
async def clear_cart(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    await save_cart(user_id, {})
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer(MSG["cart_empty"][lang])
    await show_cart(cb, user_id, lang, delete_previous=True)

# --- Checkout ---
@router.callback_query(lambda c: c.data == "checkout")
async def checkout_cb(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    cart = await load_cart(user_id)
    if not cart:
        await cb.answer(MSG["cart_empty"][lang])
        return
    await state.clear()
    buttons = [
        [("🚚 Yetkazib berish" if lang=='uz' else "🚚 Доставка", "checkout_delivery")],
        [("🏪 Filialdan olib ketish" if lang=='uz' else "🏪 Самовывоз", "checkout_pickup")]
    ]
    kb = create_inline_kb(buttons, lang=lang)
    await cb.answer()
    await send_menu_response(cb, MSG["choose_delivery"][lang], kb, delete_previous=True)

@router.callback_query(lambda c: c.data == "checkout_delivery")
async def checkout_delivery(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.set_state(UserStates.awaiting_name)
    await state.update_data(checkout_flow="delivery")
    await cb.answer()
    await send_menu_response(cb, MSG["ask_name"][lang], remove_keyboard(), delete_previous=True)

@router.callback_query(lambda c: c.data == "checkout_pickup")
async def checkout_pickup(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await state.set_state(UserStates.awaiting_pickup_name)
    await state.update_data(checkout_flow="pickup")
    await cb.answer()
    await send_menu_response(cb, MSG["ask_name"][lang], remove_keyboard(), delete_previous=True)

@router.message(UserStates.awaiting_name)
async def handle_name(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    text = sanitize_input(message.text)
    if not text or len(text) < 2:
        await message.answer(MSG["invalid_input"][lang])
        return
    await state.update_data(checkout_name=text)
    user = await load_user(user_id)
    user["name"] = text
    await save_user(user_id, user)
    await state.set_state(UserStates.awaiting_phone)
    saved_phone = user.get("phone")
    if saved_phone:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
            [KeyboardButton(text=saved_phone)],
            [KeyboardButton(text=("📞 Kontaktni yuborish" if lang=='uz' else "📞 Отправить контакт"), request_contact=True)],
            [KeyboardButton(text=MSG["back"][lang])]
        ])
        await message.answer(f"📞 Saqlangan telefon: {saved_phone}\nYoki yangi raqam yuboring:", reply_markup=kb)
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
            [KeyboardButton(text=("📞 Kontaktni yuborish" if lang=='uz' else "📞 Отправить контакт"), request_contact=True)],
            [KeyboardButton(text=MSG["back"][lang])]
        ])
        await message.answer(MSG["ask_contact"][lang], reply_markup=kb)

@router.message(UserStates.awaiting_pickup_name)
async def handle_pickup_name(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    text = sanitize_input(message.text)
    if not text or len(text) < 2:
        await message.answer(MSG["invalid_input"][lang])
        return
    await state.update_data(pickup_name=text)
    user = await load_user(user_id)
    user["name"] = text
    await save_user(user_id, user)
    await state.set_state(UserStates.awaiting_pickup_phone)
    saved_phone = user.get("phone")
    if saved_phone:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
            [KeyboardButton(text=saved_phone)],
            [KeyboardButton(text=("📞 Kontaktni yuborish" if lang=='uz' else "📞 Отправить контакт"), request_contact=True)],
            [KeyboardButton(text=MSG["back"][lang])]
        ])
        await message.answer(f"📞 Saqlangan telefon: {saved_phone}\nYoki yangi raqam yuboring:", reply_markup=kb)
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
            [KeyboardButton(text=("📞 Kontaktni yuborish" if lang=='uz' else "📞 Отправить контакт"), request_contact=True)],
            [KeyboardButton(text=MSG["back"][lang])]
        ])
        await message.answer(MSG["ask_contact"][lang], reply_markup=kb)

@router.message(UserStates.awaiting_phone)
async def handle_phone_text(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    text = sanitize_input(message.text)
    if not validate_phone(text):
        await message.answer(MSG["invalid_phone"][lang])
        return
    await state.update_data(checkout_phone=text)
    user = await load_user(user_id)
    user["phone"] = text
    await save_user(user_id, user)
    await state.set_state(UserStates.awaiting_address)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
        [KeyboardButton(text=MSG["back"][lang])]
    ])
    await message.answer(MSG["ask_address"][lang], reply_markup=kb)

@router.message(UserStates.awaiting_pickup_phone)
async def handle_pickup_phone_text(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    text = sanitize_input(message.text)
    if not validate_phone(text):
        await message.answer(MSG["invalid_phone"][lang])
        return
    await state.update_data(pickup_phone=text)
    user = await load_user(user_id)
    user["phone"] = text
    await save_user(user_id, user)
    await state.set_state(UserStates.awaiting_pickup_branch)
    buttons = [[(b['name_uz'] if lang=='uz' else b['name_ru'], f"pickup_branch_{b['id']}")] for b in BRANCHES]
    kb = create_inline_kb(buttons, include_back_menu=True, lang=lang)
    await message.answer(("🏬 Qaysi filialdan olasiz?" if lang=='uz' else "🏬 Из какого филиала вы заберете?"), reply_markup=kb)

@router.message(F.contact)
async def got_contact(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    phone = sanitize_input(message.contact.phone_number)
    if not validate_phone(phone):
        await message.answer(MSG["invalid_phone"][lang])
        return
    user = await load_user(user_id)
    user["phone"] = phone
    await save_user(user_id, user)
    current_state = await state.get_state()
    if current_state == UserStates.awaiting_phone:
        await state.update_data(checkout_phone=phone)
        await state.set_state(UserStates.awaiting_address)
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
            [KeyboardButton(text=MSG["back"][lang])]
        ])
        await message.answer(MSG["ask_address"][lang], reply_markup=kb)
    elif current_state == UserStates.awaiting_pickup_phone:
        await state.update_data(pickup_phone=phone)
        await state.set_state(UserStates.awaiting_pickup_branch)
        buttons = [[(b['name_uz'] if lang=='uz' else b['name_ru'], f"pickup_branch_{b['id']}")] for b in BRANCHES]
        kb = create_inline_kb(buttons, include_back_menu=True, lang=lang)
        await message.answer(("🏬 Qaysi filialdan olasiz?" if lang=='uz' else "🏬 Из какого филиала вы заберете?"), reply_markup=kb)
    else:
        await message.answer("✅ Kontakt qabul qilindi.", reply_markup=main_menu_kb(lang))

@router.message(UserStates.awaiting_address)
async def handle_address(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    text = sanitize_input(message.text)
    if not text or len(text) < 5:
        await message.answer(MSG["invalid_input"][lang])
        return
    await state.update_data(checkout_address=text)
    user = await load_user(user_id)
    user["address"] = text
    await save_user(user_id, user)
    await state.set_state(UserStates.awaiting_location)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
        [KeyboardButton(text=("📍 Joylashuvni yuborish" if lang=='uz' else "📍 Отправить местоположение"), request_location=True)],
        [KeyboardButton(text=("❌ O'tkazib yuborish" if lang=='uz' else "❌ Пропустить"), request_contact=False)],
        [KeyboardButton(text=MSG["back"][lang])]
    ])
    await message.answer(("📍 Istasangiz lokatsiyani ham yuboring, yoki 'Skip' bosing." if lang=='uz' else "📍 Можете отправить локацию или нажмите 'Пропустить'."), reply_markup=kb)

@router.message(lambda m: m.text and m.text == "❌ O'tkazib yuborish", UserStates.awaiting_location)
async def skip_location(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await finalize_order(user_id, lang, state)

@router.message(F.location, UserStates.awaiting_location)
async def got_location(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    if not message.location:
        await message.answer(MSG["location_error"][lang])
        return
    lat = message.location.latitude
    lon = message.location.longitude
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        await message.answer(MSG["location_error"][lang])
        return
    await state.update_data(checkout_location={"lat": lat, "lon": lon})
    await message.answer(("✅ Lokatsiya qabul qilindi." if lang=='uz' else "✅ Локация принята."))
    await finalize_order(user_id, lang, state)

@router.callback_query(lambda c: c.data and c.data.startswith("pickup_branch_"))
async def pickup_branch_selected(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    branch_id = cb.data.split("_",2)[2]
    lang = (await load_user(user_id)).get("lang", "uz")
    data = await state.get_data()
    pickup_name = data.get("pickup_name")
    pickup_phone = data.get("pickup_phone")
    if not pickup_name or not pickup_phone:
        await cb.answer(get_msg("missing_pickup_info", lang))
        await state.set_state(UserStates.awaiting_pickup_name)
        await send_menu_response(cb, MSG["ask_name"][lang], remove_keyboard(), delete_previous=True)
        return
    order_id = await get_next_order_number()
    order = {
        "id": order_id,
        "user_id": user_id,
        "user_name": pickup_name,
        "phone": pickup_phone,
        "address": f"Pickup: {get_branch(branch_id)['name_uz' if lang=='uz' else 'name_ru']}",
        "branch": branch_id,
        "delivery_type": "pickup",
        "items": await load_cart(user_id),
        "status": "received",
        "created_at": get_current_time()
    }
    await save_order(order)
    user = await load_user(user_id)
    user["orders"].append(order["id"])
    await save_user(user_id, user)
    await save_cart(user_id, {})
    await state.clear()
    await cb.answer()
    order_details = format_order_details(order, lang)
    await send_menu_response(cb, get_msg("order_confirm", lang, details=order_details), main_menu_kb(lang), delete_previous=True)
    await send_order_to_admin_and_channel(order, lang)

async def finalize_order(user_id, lang, state: FSMContext):
    data = await state.get_data()
    cart = await load_cart(user_id)
    if not cart:
        await state.clear()
        await bot.send_message(user_id, MSG["cart_empty"][lang], reply_markup=main_menu_kb(lang))
        return
    user = await load_user(user_id)
    order_id = await get_next_order_number()
    order = {
        "id": order_id,
        "user_id": user_id,
        "user_name": data.get("checkout_name") or user.get("name", "Noma'lum"),
        "phone": data.get("checkout_phone") or user.get("phone", "Noma'lum"),
        "address": data.get("checkout_address", "Noma'lum"),
        "location": data.get("checkout_location"),
        "branch": user.get("selected_branch"),
        "delivery_type": "delivery",
        "items": cart,
        "status": "received",
        "created_at": get_current_time()
    }
    await save_order(order)
    user["orders"].append(order["id"])
    await save_user(user_id, user)
    await save_cart(user_id, {})
    await state.clear()
    order_details = format_order_details(order, lang)
    try:
        await bot.send_message(int(user_id), get_msg("order_confirm", lang, details=order_details), reply_markup=main_menu_kb(lang))
    except Exception as e:
        logging.error(f"Foydalanuvchiga xabar yuborishda xato (user_id: {user_id}): {e}")
    await send_order_to_admin_and_channel(order, lang)

async def send_order_to_admin_and_channel(order, lang):
    text = format_order_details(order, lang)
    custom_photos = [item["photo"] for item in order["items"].values() if item["type"] == "custom" and item.get("photo")]

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
            for photo_id in custom_photos:
                await bot.send_photo(admin_id, photo=photo_id, caption="🎂 Maxsus buyurtma rasmi" if lang == "uz" else "🎂 Фото индивидуального заказа")
        except Exception as e:
            logging.error(f"Adminga yuborishda xato (admin_id: {admin_id}): {e}")
    if ORDER_CHANNEL_ID:
        try:
            await bot.send_message(ORDER_CHANNEL_ID, text)
            for photo_id in custom_photos:
                await bot.send_photo(ORDER_CHANNEL_ID, photo=photo_id, caption="🎂 Maxsus buyurtma rasmi" if lang == "uz" else "🎂 Фото индивидуального заказа")
        except Exception as e:
            logging.error(f"Guruhga yuborishda xato (channel_id: {ORDER_CHANNEL_ID}): {e}")

# --- Buyurtmalarim bo'limi ---
@router.message(lambda m: m.text and m.text.startswith("📦 "))
async def menu_orders_text(message: Message):
    user_id = str(message.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await menu_orders_common(message, user_id, lang)

@router.callback_query(lambda c: c.data == "menu_orders")
async def menu_orders_cb(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz")
    await cb.answer()
    await menu_orders_common(cb, user_id, lang)

async def menu_orders_common(context, user_id, lang):
    user_orders = await load_user_orders(user_id)
    if not user_orders:
        await send_menu_response(context, MSG["no_orders"][lang], create_inline_kb([], lang=lang), delete_previous=True)
        return
    table_header = "| 🆔 ID | 🏬 Filial | 📊 Holat | 🕒 Vaqt |\n|-------|--------|-------|-----|\n"
    table_rows = []
    for o in sorted(user_orders, key=lambda x: x["created_at"], reverse=True):
        status = STATUS_MAP.get(o.get("status", ""), {"uz": "N/A", "ru": "N/A"})[lang]
        created = o.get("created_at", "N/A")[:10]
        branch = get_branch(o.get("branch"))
        branch_name = branch['name_uz'] if lang == "uz" and branch else (branch['name_ru'] if branch else "N/A")
        table_rows.append(f"| {o['id']} | {branch_name} | {status} | {created} |")
    text = f"📦 {MSG['menu_orders'][lang]}:\n\n{table_header}{'\n'.join(table_rows)}"
    await send_menu_response(context, text, create_inline_kb([], lang=lang), delete_previous=True)

@router.message(lambda m: m.text and m.text.startswith("/update_order"))
async def update_order_status(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        lang = (await load_user(str(user_id))).get("lang", "uz")
        await message.reply(MSG["not_admin"][lang])
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.reply("Foydalanish: /update_order ord_id new_status (received, preparing, delivered)")
        return
    order_id, new_status = parts[1].strip(), parts[2].strip().lower()
    if new_status not in STATUS_MAP:
        await message.reply("Noto‘g‘ri holat. Faqat received, preparing, delivered ishlatiladi.")
        return
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT order_data FROM orders WHERE order_id = ?", (order_id,))
        row = await cursor.fetchone()
        if row:
            order = json.loads(row[0])
            order["status"] = new_status
            await update_order(order_id, order)
            await message.reply(f"✅ Buyurtma {order_id} holati yangilandi: {new_status}")
            try:
                uid = int(order["user_id"])
                user_lang = (await load_user(order["user_id"])).get("lang", "uz")
                status_msg = STATUS_MAP.get(new_status, {"uz": new_status, "ru": new_status})[user_lang]
                await bot.send_message(uid, f"📊 Buyurtma {order_id} holati yangilandi: {status_msg}")
            except Exception as e:
                logging.error(f"Mijozga status yuborishda xato (user_id: {order['user_id']}): {e}")
            return
    await message.reply(f"❌ Buyurtma {order_id} topilmadi.")

@router.message(lambda m: m.text and m.text == "/list_orders")
async def list_orders(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        lang = (await load_user(str(user_id))).get("lang", "uz")
        await message.reply(MSG["not_admin"][lang])
        return
    orders = await load_orders()
    if not orders:
        await message.reply("Buyurtmalar topilmadi.")
        return
    text = "📋 Barcha buyurtmalar:\n\n"
    for o in orders:
        text += f"�ID {o['id']} | Holat: {o['status']} | User: {sanitize_input(o['user_name'])} | Vaqt: {o['created_at'][:10]}\n"
    await message.reply(text)

# --- Xato handler ---
@router.errors()
async def on_error(update, exception):
    user_id = str(getattr(update, "message", None) or getattr(update, "callback_query", None).from_user.id)
    lang = (await load_user(user_id)).get("lang", "uz") if user_id else "uz"
    error_msg = {
        "aiogram.exceptions.TelegramForbiddenError": "Bot bloklangan yoki foydalanuvchi xabarni qabul qila olmaydi.",
        "aiogram.exceptions.TelegramBadRequest": "Noto‘g‘ri so‘rov yuborildi.",
        "AttributeError": "Noto‘g‘ri kiritish. Iltimos, faqat matnli xabarlardan foydalaning."
    }.get(exception.__class__.__name__, "❌ Xato yuz berdi.")
    logging.exception(f"Xato: {exception}")
    try:
        await bot.send_message(user_id, f"{error_msg} Iltimos, /start bilan qayta boshlang.", reply_markup=main_menu_kb(lang))
    except Exception as e:
        logging.error(f"Xato xabarini yuborishda muammo: {e}")
        await notify_admins(f"⚠️ Foydalanuvchiga xato xabari yuborishda muammo: {e}")
    return True

async def main():
    logging.info("Bot ishga tushmoqda...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

