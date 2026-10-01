import os
import sqlite3
import asyncio
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from dotenv import load_dotenv


# =========================
# SOZLAMALAR
# =========================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

bot = Bot(TOKEN)
dp = Dispatcher()

DB_NAME = "shop.db"

# Buyurtmalar kimga yuborilishi uchun:
# Render Environment Variables ichida ADMIN_ID qo'yiladi.
ADMIN_ID = os.getenv("ADMIN_ID")


# =========================
# DATABASE
# =========================

def get_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            items TEXT NOT NULL,
            total INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Yangi',
            created_at TEXT NOT NULL
        )
    """)

    db.commit()
    db.close()


def seed_products():
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    count = cur.fetchone()[0]

    if count == 0:
        products = [
            ("Non", 5000),
            ("Sut 1 litr", 10000),
            ("Shakar 1 kg", 12000),
            ("Choy", 18000),
        ]

        cur.executemany(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            products
        )

    db.commit()
    db.close()


# =========================
# KLAVIATURA
# =========================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🛍 Mahsulotlar",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                text="🛒 Savat",
                callback_data="cart"
            ),
            InlineKeyboardButton(
                text="📝 Buyurtma berish",
                callback_data="order"
            )
        ],
        [
            InlineKeyboardButton(
                text="📦 Buyurtmalar",
                callback_data="orders"
            ),
            InlineKeyboardButton(
                text="📞 Aloqa",
                callback_data="contact"
            )
        ]
    ])


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🏠 Bosh menyu",
                callback_data="home"
            )
        ]
    ])


def products_keyboard():
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id, name, price FROM products")
    products = cur.fetchall()

    db.close()

    buttons = []

    for product_id, name, price in products:
        buttons.append([
            InlineKeyboardButton(
                text=f"{name} — {price:,} so'm",
                callback_data=f"add_to_cart:{product_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🛒 Savat",
            callback_data="cart"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="🏠 Bosh menyu",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_order_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Buyurtmani tasdiqlash",
                callback_data="confirm_order"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="cancel_order"
            )
        ]
    ])


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📞 Telefon raqamimni yuborish",
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# =========================
# BUYURTMA HOLATLARI
# =========================

order_states = {}


# =========================
# /START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🛍 Assalomu alaykum!\n\n"
        "777MAZ Magazin botiga xush kelibsiz!\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=main_menu()
    )


# =========================
# MAHSULOTLAR
# =========================

@dp.callback_query(F.data == "products")
async def products_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍 Mahsulotlar:\n\n"
        "Kerakli mahsulotni tanlang:",
        reply_markup=products_keyboard()
    )

    await callback.answer()


# =========================
# SAVATGA QO‘SHISH
# =========================

@dp.callback_query(F.data.startswith("add_to_cart:"))
async def add_to_cart(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT name, price FROM products WHERE id = ?",
        (product_id,)
    )

    product = cur.fetchone()

    if not product:
        db.close()
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return

    name, price = product

    cur.execute(
        "SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?",
        (user_id, product_id)
    )

    existing = cur.fetchone()

    if existing:
        cur.execute(
            """
            UPDATE cart
            SET quantity = quantity + 1
            WHERE user_id = ? AND product_id = ?
            """,
            (user_id, product_id)
        )
    else:
        cur.execute(
            """
            INSERT INTO cart (user_id, product_id, quantity)
            VALUES (?, ?, 1)
            """,
            (user_id, product_id)
        )

    db.commit()
    db.close()

    await callback.answer(
        f"✅ {name} savatga qo‘shildi"
    )


# =========================
# SAVAT
# =========================

@dp.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT products.name, products.price, cart.quantity
        FROM cart
        JOIN products ON products.id = cart.product_id
        WHERE cart.user_id = ?
    """, (user_id,))

    items = cur.fetchall()
    db.close()

    if not items:
        await callback.message.edit_text(
            "🛒 Savatingiz hozircha bo‘sh.",
            reply_markup=back_home()
        )
        await callback.answer()
        return

    text = "🛒 SIZNING SAVATINGIZ\n\n"

    total = 0

    for name, price, quantity in items:
        summa = price * quantity
        total += summa

        text += (
            f"• {name}\n"
            f"  {quantity} dona × {price:,} so'm = "
            f"{summa:,} so'm\n\n"
        )

    text += f"💰 Jami: {total:,} so'm"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📝 Buyurtma berish",
                callback_data="order"
            )
        ],
        [
            InlineKeyboardButton(
                text="🛍 Yana mahsulot olish",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏠 Bosh menyu",
                callback_data="home"
            )
        ]
    ])

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================
# BUYURTMA BOSHLASH
# =========================

@dp.callback_query(F.data == "order")
async def order_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT products.name, products.price, cart.quantity
        FROM cart
        JOIN products ON products.id = cart.product_id
        WHERE cart.user_id = ?
    """, (user_id,))

    items = cur.fetchall()
    db.close()

    if not items:
        await callback.answer(
            "Avval mahsulotlarni savatga qo‘shing 🛒",
            show_alert=True
        )
        return

    order_states[user_id] = {
        "step": "name",
        "name": "",
        "phone": "",
        "address": ""
    }

    await callback.message.answer(
        "📝 BUYURTMA BERISH\n\n"
        "1️⃣ Ismingizni yozing:"
    )

    await callback.answer()


# =========================
# TELEFON
# =========================

@dp.message(F.contact)
async def contact_received(message: Message):
    user_id = message.from_user.id

    if user_id not in order_states:
        return

    state = order_states[user_id]

    if state["step"] != "phone":
        return

    state["phone"] = message.contact.phone_number
    state["step"] = "address"

    await message.answer(
        "📍 Endi yetkazib berish manzilingizni yozing:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="❌ Bekor qilish")
                ]
            ],
            resize_keyboard=True
        )
    )


# =========================
# BUYURTMA MATNLARI
# =========================

@dp.message()
async def order_messages(message: Message):
    user_id = message.from_user.id

    if user_id not in order_states:
        return

    state = order_states[user_id]
    text = message.text or ""

    if text == "❌ Bekor qilish":
        order_states.pop(user_id, None)

        await message.answer(
            "❌ Buyurtma bekor qilindi.",
            reply_markup=main_menu()
        )
        return

    # ISM
    if state["step"] == "name":
        if len(text.strip()) < 2:
            await message.answer(
                "Iltimos, ismingizni to‘liqroq yozing:"
            )
            return

        state["name"] = text.strip()
        state["step"] = "phone"

        await message.answer(
            "📞 Telefon raqamingizni yuboring:\n\n"
            "Pastdagi tugmani bosishingiz mumkin.",
            reply_markup=phone_keyboard()
        )

        return

    # TELEFON
    if state["step"] == "phone":
        phone = text.strip()

        if len(phone) < 7:
            await message.answer(
                "📞 Telefon raqamni to‘g‘ri kiriting:"
            )
            return

        state["phone"] = phone
        state["step"] = "address"

        await message.answer(
            "📍 Yetkazib berish manzilingizni yozing:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(text="❌ Bekor qilish")
                    ]
                ],
                resize_keyboard=True
            )
        )

        return

    # MANZIL
    if state["step"] == "address":
        if len(text.strip()) < 5:
            await message.answer(
                "📍 Iltimos, manzilni to‘liqroq yozing:"
            )
            return

        state["address"] = text.strip()

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT products.name, products.price, cart.quantity
            FROM cart
            JOIN products ON products.id = cart.product_id
            WHERE cart.user_id = ?
        """, (user_id,))

        items = cur.fetchall()
        db.close()

        if not items:
            order_states.pop(user_id, None)

            await message.answer(
                "🛒 Savatingiz bo‘sh.",
                reply_markup=main_menu()
            )
            return

        total = 0
        items_text = ""

        for name, price, quantity in items:
            summa = price * quantity
            total += summa

            items_text += (
                f"• {name} — {quantity} dona\n"
                f"  {summa:,} so'm\n"
            )

        state["items"] = items_text
        state["total"] = total

        await message.answer(
            "📋 BUYURTMA MA'LUMOTLARI\n\n"
            f"👤 Ism: {state['name']}\n"
            f"📞 Telefon: {state['phone']}\n"
            f"📍 Manzil: {state['address']}\n\n"
            f"🛍 Mahsulotlar:\n{items_text}\n"
            f"💰 Jami: {total:,} so'm\n\n"
            "Buyurtmani tasdiqlaysizmi?",
            reply_markup=confirm_order_keyboard()
        )

        return


# =========================
# BUYURTMANI TASDIQLASH
# =========================

@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in order_states:
        await callback.answer(
            "Buyurtma ma'lumotlari topilmadi.",
            show_alert=True
        )
        return

    state = order_states[user_id]

    db = get_db()
    cur = db.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO orders
        (user_id, name, phone, address, items, total, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        state["name"],
        state["phone"],
        state["address"],
        state["items"],
        state["total"],
        "Yangi",
        created_at
    ))

    order_id = cur.lastrowid

    # Savatni tozalash
    cur.execute(
        "DELETE FROM cart WHERE user_id = ?",
        (user_id,)
    )

    db.commit()
    db.close()

    # Holatni o‘chirish
    order_states.pop(user_id, None)

    # Foydalanuvchiga
    await callback.message.answer(
        "✅ BUYURTMANGIZ QABUL QILINDI!\n\n"
        f"📦 Buyurtma №{order_id}\n"
        f"💰 Jami: {state['total']:,} so'm\n\n"
        "Tez orada siz bilan bog‘lanamiz.",
        reply_markup=main_menu()
    )

    # ADMIN ga yuborish
    if ADMIN_ID:
        try:
            await bot.send_message(
                int(ADMIN_ID),
                "🔔 YANGI BUYURTMA!\n\n"
                f"📦 Buyurtma №{order_id}\n\n"
                f"👤 Ism: {state['name']}\n"
                f"📞 Telefon: {state['phone']}\n"
                f"📍 Manzil: {state['address']}\n\n"
                f"🛍 Mahsulotlar:\n{state['items']}\n"
                f"💰 Jami: {state['total']:,} so'm\n\n"
                f"🕐 {created_at}"
            )
        except Exception as e:
            print("Admin xabari xatosi:", e)

    await callback.answer()


# =========================
# BUYURTMANI BEKOR QILISH
# =========================

@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback: CallbackQuery):
    user_id = callback.from_user.id

    order_states.pop(user_id, None)

    await callback.message.answer(
        "❌ Buyurtma bekor qilindi.",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# BUYURTMALAR
# =========================

@dp.callback_query(F.data == "orders")
async def orders_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT id, total, status, created_at
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,))

    orders = cur.fetchall()
    db.close()

    if not orders:
        await callback.message.edit_text(
            "📦 Sizda hozircha buyurtmalar yo‘q.",
            reply_markup=back_home()
        )
        await callback.answer()
        return

    text = "📦 BUYURTMALARIM\n\n"

    for order_id, total, status, created_at in orders:
        text += (
            f"№{order_id}\n"
            f"💰 {total:,} so'm\n"
            f"📌 Holat: {status}\n"
            f"🕐 {created_at}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_home()
    )

    await callback.answer()


# =========================
# ALOQA
# =========================

@dp.callback_query(F.data == "contact")
async def contact_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "📞 Aloqa\n\n"
        "Telefon: +998 XX XXX XX XX\n"
        "📍 Manzil: Mirzo Ulug‘bek tumani",
        reply_markup=back_home()
    )

    await callback.answer()


# =========================
# BOSH MENYU
# =========================

@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 Bosh menyu\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# WEBHOOK
# =========================

async def webhook(request: web.Request):
    try:
        data = await request.json()

        update = Update.model_validate(
            data,
            context={"bot": bot}
        )

        await dp.feed_update(bot, update)

        return web.Response(text="OK")

    except Exception as e:
        print("Webhook error:", e)

        return web.Response(
            text="ERROR",
            status=500
        )


# =========================
# HEALTH CHECK
# =========================

async def health(request: web.Request):
    return web.Response(
        text="777MAZ bot is running"
    )


# =========================
# STARTUP
# =========================

async def on_startup(app):
    init_db()
    seed_products()

    base_url = os.environ.get("RENDER_EXTERNAL_URL")

    if not base_url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL topilmadi"
        )

    secret = os.environ.get(
        "WEBHOOK_SECRET",
        "777maz-secret"
    )

    webhook_url = f"{base_url}/webhook/{secret}"

    await bot.set_webhook(webhook_url)

    print(
        f"Webhook set: {webhook_url}"
    )


# =========================
# CLEANUP
# =========================

async def on_cleanup(app):
    try:
        await bot.delete_webhook()
    except Exception as e:
        print("Webhook delete error:", e)

    await bot.session.close()


# =========================
# APP
# =========================

def create_app():
    app = web.Application()

    secret = os.environ.get(
        "WEBHOOK_SECRET",
        "777maz-secret"
    )

    app.router.add_get(
        "/",
        health
    )

    app.router.add_post(
        f"/webhook/{secret}",
        webhook
    )

    app.on_startup.append(
        on_startup
    )

    app.on_cleanup.append(
        on_cleanup
    )

    return app


# =========================
# RUN
# =========================

if __name__ == "__main__":
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                "10000"
            )
        )
    )
