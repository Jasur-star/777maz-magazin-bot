
import asyncio
import os
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Update
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

bot = Bot(TOKEN)
dp = Dispatcher()
DB = "shop.db"

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            product_id INTEGER,
            qty INTEGER NOT NULL,
            UNIQUE(user_id, product_id)
        )
    """)
    con.commit()
    con.close()

def seed_products():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO products(name, price, category) VALUES (?, ?, ?)",
            [
                ("Non", 5000, "Oziq-ovqat"),
                ("Sut 1 litr", 10000, "Sut mahsulotlari"),
                ("Shakar 1 kg", 12000, "Oziq-ovqat"),
                ("Choy", 18000, "Ichimliklar"),
            ],
        )
    con.commit()
    con.close()

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Mahsulotlar", callback_data="products")],
        [InlineKeyboardButton(text="🛒 Savat", callback_data="cart")],
        [InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="orders")],
        [InlineKeyboardButton(text="📞 Aloqa", callback_data="contact")],
    ])

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🏪 777MAZ Magazin botiga xush kelibsiz!\n\nKerakli bo‘limni tanlang:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "products")
async def products(call: CallbackQuery):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT id, name, price FROM products ORDER BY category, name")
    rows = cur.fetchall()
    con.close()

    buttons = [[InlineKeyboardButton(
        text=f"{name} — {price:,} so‘m",
        callback_data=f"add:{pid}"
    )] for pid, name, price in rows]
    buttons.append([InlineKeyboardButton(text="🛒 Savat", callback_data="cart")])
    await call.message.edit_text(
        "🛍 Mahsulotlar:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()

@dp.callback_query(F.data.startswith("add:"))
async def add_to_cart(call: CallbackQuery):
    pid = int(call.data.split(":")[1])
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO cart(user_id, product_id, qty) VALUES (?, ?, 1)
        ON CONFLICT(user_id, product_id) DO UPDATE SET qty = qty + 1
    """, (call.from_user.id, pid))
    con.commit()
    con.close()
    await call.answer("✅ Savatga qo‘shildi")

@dp.callback_query(F.data == "cart")
async def cart(call: CallbackQuery):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT p.name, p.price, c.qty
        FROM cart c JOIN products p ON p.id = c.product_id
        WHERE c.user_id = ?
    """, (call.from_user.id,))
    rows = cur.fetchall()
    con.close()

    if not rows:
        text = "🛒 Savat hozircha bo‘sh."
    else:
        lines = ["🛒 Savatingiz:\n"]
        for name, price, qty in rows:
            lines.append(f"• {name} × {qty} = {price * qty:,} so‘m")
        total = sum(price * qty for _, price, qty in rows)
        lines.append(f"\n💰 Jami: {total:,} so‘m")
        text = "\n".join(lines)

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 Mahsulotlarga qaytish", callback_data="products")],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")],
        ])
    )
    await call.answer()

@dp.callback_query(F.data == "contact")
async def contact(call: CallbackQuery):
    await call.message.edit_text(
        "📞 Aloqa\n\nTelefon: +998 XX XXX XX XX\n📍 Manzil: keyin qo‘shamiz.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data == "orders")
async def orders(call: CallbackQuery):
    await call.answer("📦 Buyurtmalar bo‘limini keyingi bosqichda qo‘shamiz.")

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text(
        "🏪 777MAZ Magazin\n\nKerakli bo‘limni tanlang:",
        reply_markup=main_menu()
    )
    await call.answer()

async def webhook(request: web.Request):
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response(text="OK")
    except Exception as exc:
        print("Webhook error:", repr(exc))
        return web.Response(status=500, text="ERROR")

async def health(request: web.Request):
    return web.Response(text="777MAZ bot is running")

async def on_startup(app: web.Application):
    init_db()
    seed_products()
    base_url = os.environ.get("RENDER_EXTERNAL_URL")
    secret = os.environ.get("WEBHOOK_SECRET", "777maz-secret")
    if not base_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is not available")
    webhook_url = f"{base_url}/webhook/{secret}"
    await bot.set_webhook(webhook_url)
    print("Webhook set:", webhook_url)

async def on_cleanup(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

def create_app():
    app = web.Application()
    secret = os.environ.get("WEBHOOK_SECRET", "777maz-secret")
    app.router.add_get("/", health)
    app.router.add_post(f"/webhook/{secret}", webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
