import os
import asyncio
import sqlite3
from datetime import datetime
from urllib.parse import quote

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message, CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

bot = Bot(TOKEN)
dp = Dispatcher()

DB_NAME = "shop.db"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()

ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
PRIMARY_ADMIN_ID = "8082110485"

CONTACT_PHONE = os.getenv("CONTACT_PHONE", "+998 99 690 24 07")
DEFAULT_ADDRESS = os.getenv(
    "SHOP_ADDRESS",
    "Toshkent shahar, Mirzo Ulug‘bek tumani, Mirzo Ulug‘bek ko‘chasi, 107-uy, 1-xonadon"
)
DEFAULT_TELEGRAM = os.getenv("SHOP_TELEGRAM", "@online08981")

WEB_MARKET_URL = os.getenv(
    "WEB_MARKET_URL",
    "https://seven77maz-magazin-bot-1.onrender.com"
).rstrip("/")

CATEGORIES = [
    "🥤 Ichimliklar",
    "🍫 Shirinliklar",
    "🍎 Mevalar",
    "🥕 Sabzavotlar",
    "👶 Bolalar ovqati",
    "🍳 Oshxona mahsulotlari",
    "🧴 Gellar va shampunlar"
]

order_states = {}
admin_states = {}
profile_states = {}
search_states = set()


# =========================
# SUPABASE
# =========================

async def supabase_request(method, path, payload=None):
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return None

    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    async with aiohttp.ClientSession() as session:
        kwargs = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload

        async with session.request(
            method,
            f"{SUPABASE_URL}/rest/v1/{path}",
            **kwargs
        ) as response:
            if response.status >= 400:
                error = await response.text()
                raise RuntimeError(f"Supabase {response.status}: {error}")

            if response.status == 204:
                return []

            text = await response.text()
            if not text:
                return []

            return await response.json()


# =========================
# DATABASE
# =========================

def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        category TEXT DEFAULT '🍳 Oshxona mahsulotlari',
        image_file_id TEXT,
        old_price INTEGER DEFAULT 0,
        is_discount INTEGER DEFAULT 0,
        is_new INTEGER DEFAULT 0
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS cart(
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(user_id, product_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        items TEXT NOT NULL,
        total INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Yangi',
        created_at TEXT NOT NULL,
        payment_method TEXT DEFAULT 'Naqd',
        latitude REAL,
        longitude REAL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS profiles(
        user_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        latitude REAL,
        longitude REAL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS favorites(
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        PRIMARY KEY(user_id, product_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    )""")

    for table, col, definition in [
        ("products", "category", "TEXT DEFAULT '🍳 Oshxona mahsulotlari'"),
        ("products", "image_file_id", "TEXT"),
        ("products", "old_price", "INTEGER DEFAULT 0"),
        ("products", "is_discount", "INTEGER DEFAULT 0"),
        ("products", "is_new", "INTEGER DEFAULT 0"),
        ("orders", "payment_method", "TEXT DEFAULT 'Naqd'"),
        ("orders", "latitude", "REAL"),
        ("orders", "longitude", "REAL"),
        ("profiles", "latitude", "REAL"),
        ("profiles", "longitude", "REAL")
    ]:
        cur.execute(f"PRAGMA table_info({table})")
        columns = [r[1] for r in cur.fetchall()]
        if col not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

    defaults = {
        "contact_phone": CONTACT_PHONE,
        "shop_address": DEFAULT_ADDRESS,
        "telegram": DEFAULT_TELEGRAM,
    }

    for k, v in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (k, v)
        )

    con.commit()
    con.close()


def setting(key, fallback=""):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = cur.fetchone()
    con.close()
    return r[0] if r else fallback


def set_setting(key, value):
    con = db()
    con.execute(
        """INSERT INTO settings(key,value)
           VALUES(?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, value)
    )
    con.commit()
    con.close()


def seed_products():
    con = db()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            """INSERT INTO products
               (name,price,category,image_file_id,old_price,is_discount,is_new)
               VALUES(?,?,?,?,?,?,?)""",
            [
                ("Sut 1 litr", 10000, "🥤 Ichimliklar", None, 0, 0, 0),
                ("Choy", 18000, "🥤 Ichimliklar", None, 0, 0, 0),
                ("Shakar 1 kg", 12000, "🍫 Shirinliklar", None, 0, 0, 0),
                ("Non", 5000, "🍳 Oshxona mahsulotlari", None, 0, 0, 0)
            ]
        )

    con.commit()
    con.close()


# =========================
# HELPERS
# =========================

def is_admin(uid):
    uid = str(uid).strip()
    allowed = {PRIMARY_ADMIN_ID}
    if ADMIN_ID:
        allowed.add(ADMIN_ID)
    return uid in allowed


def admin_chat_id():
    value = ADMIN_ID or PRIMARY_ADMIN_ID
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clear_user_states(uid):
    order_states.pop(uid, None)
    admin_states.pop(uid, None)
    search_states.discard(uid)


def profile_get(uid):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT name,phone,address,latitude,longitude FROM profiles WHERE user_id=?",
        (uid,)
    )
    r = cur.fetchone()
    con.close()
    return r or ("", "", "", None, None)


def profile_save(uid, name=None, phone=None, address=None, lat=None, lon=None):
    old = profile_get(uid)

    vals = (
        name if name is not None else old[0],
        phone if phone is not None else old[1],
        address if address is not None else old[2],
        lat if lat is not None else old[3],
        lon if lon is not None else old[4]
    )

    con = db()
    con.execute(
        """INSERT INTO profiles(user_id,name,phone,address,latitude,longitude)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
           name=excluded.name,
           phone=excluded.phone,
           address=excluded.address,
           latitude=excluded.latitude,
           longitude=excluded.longitude""",
        (uid, *vals)
    )
    con.commit()
    con.close()


# =========================
# KEYBOARDS
# =========================

def main_menu():
    # Asosiy menyu: faqat 3 ta bo‘lim
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🛍 Mahsulotlar bo‘limi",
            callback_data="products"
        )],
        [InlineKeyboardButton(
            text="🛒 Savat",
            callback_data="cart"
        )],
        [InlineKeyboardButton(
            text="☎️ Biz bilan aloqa",
            callback_data="contact"
        )]
    ])


async def safe_edit(c, text, reply_markup=None):
    """Edit callback message safely for both text and photo messages."""
    msg = c.message
    if msg is None:
        return

    try:
        if getattr(msg, "photo", None):
            await msg.edit_caption(
                caption=text,
                reply_markup=reply_markup
            )
        else:
            await msg.edit_text(
                text,
                reply_markup=reply_markup
            )
    except TelegramBadRequest as e:
        # Some Telegram messages cannot be edited anymore.
        # Send a fresh message instead of returning webhook 500.
        print("Safe edit fallback:", repr(e))
        await msg.answer(
            text,
            reply_markup=reply_markup
        )


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Mahsulot qo‘shish", callback_data="admin_add")],
        [
            InlineKeyboardButton(
                text="🏷️ Chegirmali mahsulot",
                callback_data="admin_add_discount"
            ),
            InlineKeyboardButton(
                text="🆕 Yangi mahsulot",
                callback_data="admin_add_new"
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 Mahsulotlar",
                callback_data="admin_list"
            ),
            InlineKeyboardButton(
                text="🗑 O‘chirish",
                callback_data="admin_delete"
            )
        ],
        [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="admin_settings")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
    ])


def admin_cat_keyboard():
    rows = [
        [
            InlineKeyboardButton(
                text=cat,
                callback_data=f"admin_cat:{i}"
            )
        ]
        for i, cat in enumerate(CATEGORIES)
    ]

    rows.append([
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data="admin_cancel"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def catalog_keyboard():
    rows = [
        [
            InlineKeyboardButton(
                text=cat,
                callback_data=f"category:{i}"
            )
        ]
        for i, cat in enumerate(CATEGORIES)
    ]

    rows.extend([
        [
            InlineKeyboardButton(text="🏷️ Chegirmalar", callback_data="discounts"),
            InlineKeyboardButton(text="🆕 Yangilar", callback_data="new_products")
        ],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_rows(rows, back="home"):
    buttons = []

    for row in rows:
        pid = row[0]
        name = row[1]
        price = row[2]

        buttons.append([
            InlineKeyboardButton(
                text=f"🛍 {name} — {price:,} so'm",
                callback_data=f"product:{pid}"
            )
        ])

    if back == "home":
        buttons.append([
            InlineKeyboardButton(
                text="🏠 Bosh menyu",
                callback_data="home"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📞 Telefon raqamimni yuborish",
                    request_contact=True
                )
            ],
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def location_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📍 Lokatsiyamni yuborish",
                    request_location=True
                )
            ],
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Karta orqali", callback_data="pay:card")],
        [InlineKeyboardButton(text="💵 Naqd pul", callback_data="pay:cash")],
        [InlineKeyboardButton(text="🏪 Joyida to‘lov", callback_data="pay:onsite")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order")]
    ])


def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data="confirm_order"
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="cancel_order"
            )
        ]
    ])


# =========================
# TELEGRAM
# =========================

@dp.message(CommandStart())
async def start(m: Message):
    clear_user_states(m.from_user.id)

    await m.answer(
        "👋 777MAZ Marketga xush kelibsiz!\n\n"
        "🛍 Mahsulotlarni ko‘rish va buyurtma berish uchun "
        "quyidagi tugmalardan foydalaning.",
        reply_markup=main_menu()
    )


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if not is_admin(m.from_user.id):
        await m.answer("⛔ Sizda admin huquqi yo‘q.")
        return

    clear_user_states(m.from_user.id)
    await m.answer("⚙️ ADMIN PANEL", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "admin")
async def admin_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("⛔ Admin huquqi yo‘q.", show_alert=True)
        return

    clear_user_states(c.from_user.id)

    await safe_edit(c,
        "⚙️ ADMIN PANEL",
        reply_markup=admin_keyboard()
    )
    await c.answer("Admin panel")


async def begin_add(c, mode):
    if not is_admin(c.from_user.id):
        await c.answer("⛔ Admin huquqi yo‘q.", show_alert=True)
        return

    uid = c.from_user.id
    clear_user_states(uid)

    admin_states[uid] = {
        "step": "name",
        "mode": mode,
        "name": "",
        "price": 0,
        "old_price": 0,
        "category": "",
        "is_discount": int(mode == "discount"),
        "is_new": int(mode == "new")
    }

    await c.message.answer("1️⃣ Mahsulot nomini yozing:")
    await c.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add(c):
    await begin_add(c, "normal")


@dp.callback_query(F.data == "admin_add_discount")
async def admin_add_discount(c):
    await begin_add(c, "discount")


@dp.callback_query(F.data == "admin_add_new")
async def admin_add_new(c):
    await begin_add(c, "new")


@dp.callback_query(F.data.startswith("admin_cat:"))
async def admin_cat(c):
    if not is_admin(c.from_user.id):
        return

    s = admin_states.get(c.from_user.id)
    if not s:
        await c.answer("Avval mahsulot qo‘shishni boshlang.", show_alert=True)
        return

    try:
        index = int(c.data.split(":")[1])
        s["category"] = CATEGORIES[index]
    except (ValueError, IndexError):
        await c.answer("Kategoriya xatosi.", show_alert=True)
        return

    s["step"] = "old_price" if s["mode"] == "discount" else "photo"

    if s["step"] == "old_price":
        await c.message.answer("Eski narxni yozing:")
    else:
        await c.message.answer("Mahsulot rasmini yuboring 📷")

    await c.answer()


@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(c):
    if not is_admin(c.from_user.id):
        await c.answer("⛔ Admin huquqi yo‘q.", show_alert=True)
        return

    clear_user_states(c.from_user.id)

    await safe_edit(c,
        "❌ Amal bekor qilindi.\n\n⚙️ ADMIN PANEL",
        reply_markup=admin_keyboard()
    )
    await c.answer("Bekor qilindi")


@dp.message(F.photo)
async def admin_photo(m: Message):
    uid = m.from_user.id

    if not is_admin(uid):
        return

    s = admin_states.get(uid)

    if not s or s.get("step") != "photo":
        return

    image_id = m.photo[-1].file_id

    con = db()
    cur = con.cursor()

    cur.execute(
        """INSERT INTO products
           (name,price,category,image_file_id,old_price,is_discount,is_new)
           VALUES(?,?,?,?,?,?,?)""",
        (
            s["name"],
            s["price"],
            s["category"],
            image_id,
            s.get("old_price", 0),
            s.get("is_discount", 0),
            s.get("is_new", 0)
        )
    )

    pid = cur.lastrowid
    con.commit()
    con.close()

    if SUPABASE_URL and SUPABASE_SECRET_KEY:
        try:
            await supabase_request(
                "POST",
                "products?on_conflict=id",
                {
                    "id": pid,
                    "name": s["name"],
                    "price": s["price"],
                    "category": s["category"],
                    "image_file_id": image_id,
                    "old_price": s.get("old_price", 0),
                    "is_discount": bool(s.get("is_discount", 0)),
                    "is_new": bool(s.get("is_new", 0))
                }
            )
        except Exception as e:
            con = db()
            con.execute("DELETE FROM products WHERE id=?", (pid,))
            con.commit()
            con.close()

            await m.answer(f"❌ Supabase xatosi: {e}")
            return

    admin_states.pop(uid, None)

    await m.answer(
        f"✅ Mahsulot qo‘shildi!\n"
        f"ID: {pid}\n"
        f"{s['name']}\n"
        f"{s['price']:,} so'm",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_list")
async def admin_list(c):
    if not is_admin(c.from_user.id):
        return

    con = db()
    rows = con.execute(
        """SELECT id,name,price,category,old_price,is_discount,is_new
           FROM products ORDER BY id DESC"""
    ).fetchall()
    con.close()

    text = "📋 MAHSULOTLAR\n\n"

    for r in rows:
        text += (
            f"№{r[0]} — {r[1]} — {r[2]:,} so'm\n"
            f"📂 {r[3]}"
        )

        if r[4] and r[5]:
            text += f"\n🏷️ Eski: {r[4]:,}"

        if r[6]:
            text += "\n🆕 Yangi"

        text += "\n\n"

    await safe_edit(c,
        text[:3900] or "Mahsulot yo‘q.",
        reply_markup=admin_keyboard()
    )
    await c.answer()


@dp.callback_query(F.data == "admin_delete")
async def admin_delete(c):
    if not is_admin(c.from_user.id):
        return

    con = db()
    rows = con.execute(
        "SELECT id,name,price FROM products ORDER BY id DESC"
    ).fetchall()
    con.close()

    kb = [
        [
            InlineKeyboardButton(
                text=f"🗑 {n} — {p:,}",
                callback_data=f"admin_del:{pid}"
            )
        ]
        for pid, n, p in rows
    ]

    kb.append([
        InlineKeyboardButton(
            text="⬅️ Admin",
            callback_data="admin"
        )
    ])

    await safe_edit(c,
        "🗑 O‘CHIRILADIGAN MAHSULOT:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )
    await c.answer()


@dp.callback_query(F.data.startswith("admin_del:"))
async def admin_del(c):
    if not is_admin(c.from_user.id):
        return

    try:
        pid = int(c.data.split(":")[1])
    except (ValueError, IndexError):
        await c.answer("ID xatosi.", show_alert=True)
        return

    con = db()
    cur = con.cursor()

    cur.execute("SELECT name FROM products WHERE id=?", (pid,))
    r = cur.fetchone()

    if not r:
        con.close()
        await c.answer("Topilmadi", show_alert=True)
        return

    if SUPABASE_URL and SUPABASE_SECRET_KEY:
        try:
            await supabase_request(
                "DELETE",
                f"products?id=eq.{pid}"
            )
        except Exception as e:
            con.close()
            await c.answer(
                f"❌ Supabase xatosi: {e}",
                show_alert=True
            )
            return

    cur.execute("DELETE FROM cart WHERE product_id=?", (pid,))
    cur.execute("DELETE FROM favorites WHERE product_id=?", (pid,))
    cur.execute("DELETE FROM products WHERE id=?", (pid,))

    con.commit()
    con.close()

    await c.answer("✅ O‘chirildi", show_alert=True)
    await admin_delete(c)


@dp.callback_query(F.data == "admin_settings")
async def admin_settings(c):
    if not is_admin(c.from_user.id):
        return

    text = f"""📞 ALOQA / SOZLAMALAR

📞 Telefon: {setting('contact_phone')}
📍 Manzil: {setting('shop_address')}
📱 Telegram: {setting('telegram') or 'Kiritilmagan'}

Qaysi ma’lumotni o‘zgartirasiz?"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Telefon", callback_data="set:phone")],
        [InlineKeyboardButton(text="📍 Manzil", callback_data="set:address")],
        [InlineKeyboardButton(text="📱 Telegram", callback_data="set:telegram")],
        [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin")]
    ])

    await safe_edit(c, text, reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data.startswith("set:"))
async def set_start(c):
    if not is_admin(c.from_user.id):
        return

    uid = c.from_user.id
    clear_user_states(uid)

    field = c.data.split(":")[1]

    if field not in {"phone", "address", "telegram"}:
        await c.answer("Sozlama xatosi.", show_alert=True)
        return

    admin_states[uid] = {
        "step": "setting",
        "field": field
    }

    labels = {
        "phone": "📞 Yangi telefonni yozing:",
        "address": "📍 Yangi manzilni yozing:",
        "telegram": "📱 Telegram username/linkni yozing:"
    }

    await c.message.answer(labels[field])
    await c.answer()


# =========================
# CATALOG
# =========================

async def show_products(c, where="all"):
    con = db()
    cur = con.cursor()

    if where == "discount":
        cur.execute(
            """SELECT id,name,price,old_price,is_discount,is_new
               FROM products
               WHERE is_discount=1
               ORDER BY id DESC"""
        )
    elif where == "new":
        cur.execute(
            """SELECT id,name,price,old_price,is_discount,is_new
               FROM products
               WHERE is_new=1
               ORDER BY id DESC"""
        )
    else:
        try:
            category = CATEGORIES[int(where)]
        except (ValueError, IndexError):
            category = CATEGORIES[0]

        cur.execute(
            """SELECT id,name,price,old_price,is_discount,is_new
               FROM products
               WHERE category=?
               ORDER BY id DESC""",
            (category,)
        )

    rows = cur.fetchall()
    con.close()

    title = {
        "discount": "🏷️ CHEGIRMALAR",
        "new": "🆕 YANGI MAHSULOTLAR"
    }.get(where, "🛍 MAHSULOTLAR")

    await safe_edit(c,
        title + "\n\nMahsulotni tanlang:",
        reply_markup=product_rows(rows, "home")
    )
    await c.answer()


@dp.callback_query(F.data == "products")
async def products(c):
    await safe_edit(c,
        "🛍 KATALOG\n\nKategoriyani tanlang:",
        reply_markup=catalog_keyboard()
    )
    await c.answer()


@dp.callback_query(F.data.startswith("category:"))
async def category(c):
    await show_products(c, c.data.split(":")[1])


@dp.callback_query(F.data == "discounts")
async def discounts(c):
    await show_products(c, "discount")


@dp.callback_query(F.data == "new_products")
async def new_products(c):
    await show_products(c, "new")


@dp.callback_query(F.data.startswith("product:"))
async def product(c):
    try:
        pid = int(c.data.split(":")[1])
    except (ValueError, IndexError):
        await c.answer("Mahsulot ID xatosi.", show_alert=True)
        return

    con = db()

    p = con.execute(
        """SELECT name,price,category,image_file_id,old_price,is_discount,is_new
           FROM products WHERE id=?""",
        (pid,)
    ).fetchone()

    fav = con.execute(
        """SELECT 1 FROM favorites
           WHERE user_id=? AND product_id=?""",
        (c.from_user.id, pid)
    ).fetchone()

    con.close()

    if not p:
        await c.answer("Mahsulot topilmadi", show_alert=True)
        return

    name, price, cat, img, old, disc, new = p

    text = (
        f"🛍 {name}\n\n"
        f"💰 {price:,} so'm\n"
        f"📂 {cat}"
    )

    if disc and old:
        text += f"\n🏷️ Eski narx: {old:,} so'm"

    if new:
        text += "\n🆕 Yangi mahsulot"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🛒 Savatga qo‘shish",
            callback_data=f"add:{pid}"
        )],
        [InlineKeyboardButton(
            text="💔 Sevimlidan olib tashlash" if fav else "⭐ Sevimliga",
            callback_data=f"fav:{pid}"
        )],
        [
            InlineKeyboardButton(text="🛒 Savat", callback_data="cart"),
            InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")
        ]
    ])

    if img:
        await c.message.answer_photo(
            img,
            caption=text,
            reply_markup=kb
        )
    else:
        await c.message.answer(
            text,
            reply_markup=kb
        )

    await c.answer()


# =========================
# CART / FAVORITES
# =========================

@dp.callback_query(F.data.startswith("add:"))
async def add(c):
    try:
        pid = int(c.data.split(":")[1])
    except (ValueError, IndexError):
        await c.answer("ID xatosi.", show_alert=True)
        return

    uid = c.from_user.id
    con = db()

    p = con.execute(
        "SELECT name FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    if not p:
        con.close()
        await c.answer("Topilmadi", show_alert=True)
        return

    con.execute(
        """INSERT INTO cart(user_id,product_id,quantity)
           VALUES(?,?,1)
           ON CONFLICT(user_id,product_id)
           DO UPDATE SET quantity=quantity+1""",
        (uid, pid)
    )

    con.commit()
    con.close()

    await c.answer(f"✅ {p[0]} savatga qo‘shildi")


@dp.callback_query(F.data.startswith("fav:"))
async def fav(c):
    try:
        pid = int(c.data.split(":")[1])
    except (ValueError, IndexError):
        await c.answer("ID xatosi.", show_alert=True)
        return

    uid = c.from_user.id
    con = db()

    if con.execute(
        """SELECT 1 FROM favorites
           WHERE user_id=? AND product_id=?""",
        (uid, pid)
    ).fetchone():
        con.execute(
            "DELETE FROM favorites WHERE user_id=? AND product_id=?",
            (uid, pid)
        )
        msg = "💔 Olib tashlandi"
    else:
        con.execute(
            "INSERT OR IGNORE INTO favorites VALUES(?,?)",
            (uid, pid)
        )
        msg = "⭐ Saqlandi"

    con.commit()
    con.close()

    await c.answer(msg)


@dp.callback_query(F.data == "favorites")
async def favorites(c):
    con = db()

    rows = con.execute(
        """SELECT p.id,p.name,p.price,p.old_price,p.is_discount,p.is_new
           FROM favorites f
           JOIN products p ON p.id=f.product_id
           WHERE f.user_id=?""",
        (c.from_user.id,)
    ).fetchall()

    con.close()

    await safe_edit(c,
        "⭐ SEVIMLILAR\n\n" +
        ("Mahsulotni tanlang:" if rows else "Hozircha yo‘q."),
        reply_markup=product_rows(rows, "home") if rows else back_home()
    )
    await c.answer()


@dp.callback_query(F.data == "cart")
async def cart(c):
    con = db()

    rows = con.execute(
        """SELECT p.name,p.price,ca.quantity
           FROM cart ca
           JOIN products p ON p.id=ca.product_id
           WHERE ca.user_id=?""",
        (c.from_user.id,)
    ).fetchall()

    con.close()

    if not rows:
        await safe_edit(c,
            "🛒 Savat bo‘sh.",
            reply_markup=back_home()
        )
        await c.answer()
        return

    total = sum(p * q for _, p, q in rows)

    text = "🛒 SAVAT\n\n" + "".join(
        f"• {n} — {q} × {p:,} = {p*q:,} so‘m\n"
        for n, p, q in rows
    )

    text += f"\n💰 Jami: {total:,} so‘m"

    await safe_edit(c,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Buyurtma",
                callback_data="order"
            )],
            [InlineKeyboardButton(
                text="🛍 Xaridni davom ettirish",
                callback_data="products"
            )],
            [InlineKeyboardButton(
                text="🏠 Bosh menyu",
                callback_data="home"
            )]
        ])
    )
    await c.answer()


# =========================
# ORDER
# =========================

@dp.callback_query(F.data == "order")
async def order(c):
    uid = c.from_user.id

    con = db()
    count = con.execute(
        "SELECT COUNT(*) FROM cart WHERE user_id=?",
        (uid,)
    ).fetchone()[0]
    con.close()

    if not count:
        await c.answer(
            "Avval savatga mahsulot qo‘shing.",
            show_alert=True
        )
        return

    name, phone, address, lat, lon = profile_get(uid)

    order_states[uid] = {
        "step": "name",
        "name": name,
        "phone": phone,
        "address": address,
        "lat": lat,
        "lon": lon
    }

    if not name:
        await c.message.answer("📝 Ismingizni yozing:")
    elif not phone:
        order_states[uid]["step"] = "phone"
        await c.message.answer(
            "📞 Telefon:",
            reply_markup=phone_keyboard()
        )
    elif lat is None:
        order_states[uid]["step"] = "location"
        await c.message.answer(
            "📍 Yetkazib berish uchun lokatsiyangizni yuboring:",
            reply_markup=location_keyboard()
        )
    elif not address:
        order_states[uid]["step"] = "address"
        await c.message.answer(
            "📍 Ko‘cha, uy va xonadon manzilini yozing:"
        )
    else:
        order_states[uid]["step"] = "payment"
        await c.message.answer(
            "💳 To‘lov usulini tanlang:",
            reply_markup=payment_keyboard()
        )

    await c.answer()


async def preview(uid, m):
    s = order_states[uid]

    con = db()
    rows = con.execute(
        """SELECT p.name,p.price,ca.quantity
           FROM cart ca
           JOIN products p ON p.id=ca.product_id
           WHERE ca.user_id=?""",
        (uid,)
    ).fetchall()
    con.close()

    total = sum(p * q for _, p, q in rows)

    s["items"] = "".join(
        f"• {n} — {q} dona — {p*q:,} so‘m\n"
        for n, p, q in rows
    )
    s["total"] = total

    loc = ""
    if s.get("lat") is not None and s.get("lon") is not None:
        loc = (
            f"\n📍 GPS: "
            f"https://maps.google.com/?q={s['lat']},{s['lon']}"
        )

    await m.answer(
        f"""📋 BUYURTMA

👤 Ism: {s['name']}
📞 Telefon: {s['phone']}
📍 Manzil: {s['address']}{loc}
💳 To‘lov: {s.get('payment','')}

🛍 Mahsulotlar:
{s['items']}
💰 Jami: {total:,} so‘m

Tasdiqlaysizmi?""",
        reply_markup=confirm_keyboard()
    )


@dp.callback_query(F.data.startswith("pay:"))
async def pay(c):
    uid = c.from_user.id

    if uid not in order_states:
        await c.answer(
            "Buyurtmani boshlang.",
            show_alert=True
        )
        return

    labels = {
        "card": "💳 Karta orqali",
        "cash": "💵 Naqd pul",
        "onsite": "🏪 Joyida to‘lov"
    }

    key = c.data.split(":")[1]

    if key not in labels:
        await c.answer("To‘lov turi xatosi.", show_alert=True)
        return

    order_states[uid]["payment"] = labels[key]

    await preview(uid, c.message)
    await c.answer()


@dp.callback_query(F.data == "confirm_order")
async def confirm(c):
    uid = c.from_user.id
    s = order_states.get(uid)

    if not s or not s.get("payment"):
        await c.answer(
            "To‘lov usulini tanlang.",
            show_alert=True
        )
        return

    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    con = db()
    cur = con.cursor()

    cur.execute(
        """INSERT INTO orders(
           user_id,name,phone,address,items,total,status,created_at,
           payment_method,latitude,longitude)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uid,
            s["name"],
            s["phone"],
            s["address"],
            s["items"],
            s["total"],
            "Yangi",
            created,
            s["payment"],
            s.get("lat"),
            s.get("lon")
        )
    )

    oid = cur.lastrowid

    cur.execute(
        "DELETE FROM cart WHERE user_id=?",
        (uid,)
    )

    con.commit()
    con.close()

    profile_save(
        uid,
        s["name"],
        s["phone"],
        s["address"],
        s.get("lat"),
        s.get("lon")
    )

    order_states.pop(uid, None)

    await c.message.answer(
        f"✅ Buyurtma №{oid} qabul qilindi!\n"
        f"💰 {s['total']:,} so‘m",
        reply_markup=main_menu()
    )

    admin_id = admin_chat_id()

    if admin_id:
        msg = f"""🔔 YANGI BUYURTMA №{oid}

👤 {s['name']}
📞 {s['phone']}
📍 {s['address']}
💳 {s['payment']}

🛍 {s['items']}💰 Jami: {s['total']:,} so‘m
🕐 {created}"""

        try:
            await bot.send_message(admin_id, msg)

            if s.get("lat") is not None and s.get("lon") is not None:
                await bot.send_location(
                    admin_id,
                    s["lat"],
                    s["lon"]
                )
        except Exception as e:
            print("Admin xabari xatosi:", e)

    await c.answer()


@dp.callback_query(F.data == "cancel_order")
async def cancel(c):
    order_states.pop(c.from_user.id, None)

    await c.message.answer(
        "❌ Bekor qilindi.",
        reply_markup=ReplyKeyboardRemove()
    )

    await c.message.answer(
        "🏠 Bosh menyu",
        reply_markup=main_menu()
    )

    await c.answer()


@dp.callback_query(F.data == "orders")
async def orders(c):
    con = db()

    rows = con.execute(
        """SELECT id,total,status,created_at,payment_method
           FROM orders
           WHERE user_id=?
           ORDER BY id DESC
           LIMIT 10""",
        (c.from_user.id,)
    ).fetchall()

    con.close()

    text = "📦 BUYURTMALARIM\n\n" + "".join(
        f"№{oid} — {total:,} so‘m\n"
        f"📌 {status}\n"
        f"💳 {pay}\n"
        f"🕐 {created}\n\n"
        for oid, total, status, created, pay in rows
    )

    await safe_edit(c,
        text if rows else "📦 Hozircha buyurtma yo‘q.",
        reply_markup=back_home()
    )
    await c.answer()


@dp.callback_query(F.data == "payment_info")
async def payment_info(c):
    await safe_edit(c,
        "💳 To‘lov: karta, naqd yoki joyida to‘lov.",
        reply_markup=back_home()
    )
    await c.answer()


@dp.callback_query(F.data == "show_phone")
async def show_phone(c):
    phone = setting("contact_phone", CONTACT_PHONE)
    await c.answer(f"📞 {phone}", show_alert=True)


@dp.callback_query(F.data == "contact")
async def contact(c):
    phone = setting("contact_phone", CONTACT_PHONE)
    addr = setting("shop_address", DEFAULT_ADDRESS)
    tg = setting("telegram", DEFAULT_TELEGRAM)

    map_url = (
        "https://www.google.com/maps/search/?api=1&query="
        + quote(addr)
    )

    text = (
        "☎️ BIZ BILAN ALOQA\n\n"
        f"📞 Telefon: {phone}\n"
        f"💬 Telegram: {tg}\n"
        f"📍 Manzil: {addr}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📞 Telefon raqami",
            callback_data="show_phone"
        )],
        [InlineKeyboardButton(
            text="💬 Telegram",
            url="https://t.me/online08981"
        )],
        [InlineKeyboardButton(
            text="📍 Xaritada ko‘rish",
            url=map_url
        )],
        [InlineKeyboardButton(
            text="🏠 Bosh menyu",
            callback_data="home"
        )]
    ])

    await safe_edit(c, text, reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data == "profile")
async def profile(c):
    n, p, a, lat, lon = profile_get(c.from_user.id)

    text = (
        "👤 PROFIL\n\n"
        f"👤 {n or 'Kiritilmagan'}\n"
        f"📞 {p or 'Kiritilmagan'}\n"
        f"📍 {a or 'Kiritilmagan'}"
    )

    await safe_edit(c,
        text,
        reply_markup=back_home()
    )
    await c.answer()


@dp.callback_query(F.data == "search")
async def search(c):
    search_states.add(c.from_user.id)

    await c.message.answer(
        "🔎 Mahsulot nomini yozing:"
    )
    await c.answer()


@dp.message(F.location)
async def location_received(m: Message):
    uid = m.from_user.id
    lat = m.location.latitude
    lon = m.location.longitude

    if (
        uid in order_states
        and order_states[uid].get("step") == "location"
    ):
        order_states[uid]["lat"] = lat
        order_states[uid]["lon"] = lon
        order_states[uid]["step"] = "address"

        profile_save(uid, lat=lat, lon=lon)

        await m.answer(
            "✅ Lokatsiya olindi.\n"
            "📍 Endi ko‘cha, uy va xonadon manzilini yozing:",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        profile_save(uid, lat=lat, lon=lon)

        await m.answer(
            "📍 Lokatsiya saqlandi.",
            reply_markup=main_menu()
        )


@dp.message(F.contact)
async def contact_received(m: Message):
    uid = m.from_user.id

    if (
        uid in order_states
        and order_states[uid].get("step") == "phone"
    ):
        order_states[uid]["phone"] = m.contact.phone_number
        order_states[uid]["step"] = "location"

        profile_save(
            uid,
            phone=m.contact.phone_number
        )

        await m.answer(
            "📍 Endi lokatsiyangizni yuboring:",
            reply_markup=location_keyboard()
        )
    else:
        profile_save(
            uid,
            phone=m.contact.phone_number
        )

        await m.answer(
            "✅ Telefon saqlandi.",
            reply_markup=main_menu()
        )


@dp.message(F.text)
async def texts(m: Message):
    uid = m.from_user.id
    text = m.text.strip()

    if text == "❌ Bekor qilish":
        order_states.pop(uid, None)
        admin_states.pop(uid, None)

        await m.answer(
            "❌ Bekor qilindi.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if uid in search_states:
        search_states.discard(uid)

        con = db()

        rows = con.execute(
            """SELECT id,name,price,old_price,is_discount,is_new
               FROM products
               WHERE name LIKE ?
               ORDER BY id DESC
               LIMIT 30""",
            (f"%{text}%",)
        ).fetchall()

        con.close()

        await m.answer(
            "🔎 Natijalar:",
            reply_markup=(
                product_rows(rows, "home")
                if rows
                else main_menu()
            )
        )
        return

    if is_admin(uid) and uid in admin_states:
        s = admin_states[uid]

        if s.get("step") == "setting":
            key = {
                "phone": "contact_phone",
                "address": "shop_address",
                "telegram": "telegram"
            }[s["field"]]

            set_setting(key, text)
            admin_states.pop(uid, None)

            await m.answer(
                "✅ Sozlama saqlandi.",
                reply_markup=admin_keyboard()
            )
            return

        if s.get("step") == "name":
            s["name"] = text
            s["step"] = "price"

            await m.answer(
                "2️⃣ Narxni yozing:"
            )
            return

        if s.get("step") in ("price", "old_price"):
            n = text.replace(" ", "").replace(",", "")

            if not n.isdigit() or int(n) <= 0:
                await m.answer(
                    "❗ Faqat musbat raqam yozing."
                )
                return

            if s["step"] == "price":
                s["price"] = int(n)
                s["step"] = "category"

                await m.answer(
                    "3️⃣ Kategoriyani tanlang:",
                    reply_markup=admin_cat_keyboard()
                )
            else:
                s["old_price"] = int(n)
                s["step"] = "photo"

                await m.answer(
                    "📷 Rasm yuboring:"
                )

            return

    if uid not in order_states:
        return

    s = order_states[uid]

    if s["step"] == "name":
        s["name"] = text
        profile_save(uid, name=text)
        s["step"] = "phone"

        await m.answer(
            "📞 Telefon raqamingizni yuboring:",
            reply_markup=phone_keyboard()
        )

    elif s["step"] == "phone":
        s["phone"] = text
        profile_save(uid, phone=text)
        s["step"] = "location"

        await m.answer(
            "📍 Lokatsiyangizni yuboring:",
            reply_markup=location_keyboard()
        )

    elif s["step"] == "address":
        s["address"] = text
        profile_save(uid, address=text)
        s["step"] = "payment"

        await m.answer(
            "💳 To‘lov usulini tanlang:",
            reply_markup=payment_keyboard()
        )


@dp.callback_query(F.data == "home")
async def home(c):
    uid = c.from_user.id
    clear_user_states(uid)

    await safe_edit(c,
        "🏠 Bosh menyu",
        reply_markup=main_menu()
    )
    await c.answer("Bosh menyu")


# =========================
# WEB MARKET API
# =========================

def product_dict(row):
    pid, name, price, cat, img, old, disc, new = row

    return {
        "id": pid,
        "name": name,
        "price": price,
        "category": cat,
        "image_file_id": img,
        "old_price": old,
        "is_discount": bool(disc),
        "is_new": bool(new)
    }


async def web_index(request):
    return web.FileResponse("index.html")


async def api_products(request):
    if SUPABASE_URL and SUPABASE_SECRET_KEY:
        try:
            rows = await supabase_request(
                "GET",
                "products?select=id,name,price,category,image_file_id,old_price,is_discount,is_new&order=id.desc"
            )

            if rows is not None:
                return web.json_response({
                    "products": rows
                })

        except Exception as e:
            print("Supabase products error:", repr(e))

    con = db()

    rows = con.execute(
        """SELECT id,name,price,category,image_file_id,
                  old_price,is_discount,is_new
           FROM products
           ORDER BY id DESC"""
    ).fetchall()

    con.close()

    return web.json_response({
        "products": [product_dict(r) for r in rows]
    })


async def api_product_image(request):
    file_id = request.query.get("file_id", "").strip()

    if not file_id:
        return web.Response(
            status=400,
            text="file_id kerak"
        )

    try:
        tg_file = await bot.get_file(file_id)

        if not tg_file.file_path:
            return web.Response(
                status=404,
                text="Rasm topilmadi"
            )

        url = (
            f"https://api.telegram.org/file/bot"
            f"{TOKEN}/{tg_file.file_path}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return web.Response(
                        status=404,
                        text="Rasmni yuklab bo‘lmadi"
                    )

                data = await response.read()

                content_type = response.headers.get(
                    "Content-Type",
                    "image/jpeg"
                )

                return web.Response(
                    body=data,
                    content_type=content_type
                )

    except Exception as e:
        print("Product image error:", repr(e))

        return web.Response(
            status=404,
            text="Rasm topilmadi"
        )


async def api_settings(request):
    return web.json_response({
        "phone": setting(
            "contact_phone",
            CONTACT_PHONE
        ),
        "address": setting(
            "shop_address",
            DEFAULT_ADDRESS
        ),
        "telegram": setting(
            "telegram",
            DEFAULT_TELEGRAM
        )
    })


async def api_order(request):
    try:
        data = await request.json()

        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        address = str(data.get("address", "")).strip()
        lat = data.get("latitude")
        lon = data.get("longitude")
        payment = str(
            data.get("payment_method", "Naqd")
        )
        items = data.get("items", [])

        if not name or not phone or not items:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Ism, telefon va savat kerak."
                },
                status=400
            )

        # Web Market Supabase'dan mahsulot oladi.
        # Buyurtma vaqtida local DB ham sinxronlangan bo‘lishi kerak.
        con = db()

        valid = []
        total = 0

        for item in items:
            try:
                pid = int(item["id"])
                qty = max(
                    1,
                    min(
                        99,
                        int(item.get("quantity", 1))
                    )
                )
            except (ValueError, TypeError, KeyError):
                continue

            r = con.execute(
                "SELECT name,price FROM products WHERE id=?",
                (pid,)
            ).fetchone()

            if r:
                valid.append(
                    (r[0], r[1], qty)
                )
                total += r[1] * qty

        if not valid:
            con.close()

            return web.json_response(
                {
                    "ok": False,
                    "error": "Mahsulot topilmadi."
                },
                status=400
            )

        items_text = "".join(
            f"• {n} — {q} dona — {p*q:,} so‘m\n"
            for n, p, q in valid
        )

        created = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cur = con.cursor()

        cur.execute(
            """INSERT INTO orders(
               user_id,name,phone,address,items,total,status,
               created_at,payment_method,latitude,longitude)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                0,
                name,
                phone,
                address,
                items_text,
                total,
                "Yangi",
                created,
                payment,
                lat,
                lon
            )
        )

        oid = cur.lastrowid

        con.commit()
        con.close()

        admin_id = admin_chat_id()

        if admin_id:
            msg = f"""🌐 WEB MARKETDAN YANGI BUYURTMA №{oid}

👤 {name}
📞 {phone}
📍 {address}
💳 {payment}

🛍 {items_text}💰 Jami: {total:,} so‘m
🕐 {created}"""

            try:
                await bot.send_message(
                    admin_id,
                    msg
                )

                if lat is not None and lon is not None:
                    await bot.send_location(
                        admin_id,
                        float(lat),
                        float(lon)
                    )

            except Exception as e:
                print(
                    "Web order admin xabari:",
                    repr(e)
                )

        return web.json_response({
            "ok": True,
            "order_id": oid,
            "total": total
        })

    except Exception as e:
        print(
            "Web order error:",
            repr(e)
        )

        return web.json_response(
            {
                "ok": False,
                "error": "Server xatosi."
            },
            status=500
        )


# =========================
# WEBHOOK
# =========================

async def webhook(request):
    try:
        data = await request.json()
        update_id = data.get("update_id")

        print(
            f"Telegram webhook update received: {update_id}"
        )

        update = Update.model_validate(
            data,
            context={"bot": bot}
        )

        await dp.feed_update(
            bot,
            update
        )

        print(
            f"Telegram webhook update processed: {update_id}"
        )

        return web.Response(
            text="OK"
        )

    except Exception as e:
        print(
            "Webhook error:",
            repr(e)
        )

        return web.Response(
            text="ERROR",
            status=500
        )


async def health(request):
    try:
        info = await bot.get_webhook_info()

        return web.json_response({
            "ok": True,
            "service": "777MAZ bot",
            "webhook_url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
            "last_error_date": info.last_error_date,
        })

    except Exception as e:
        return web.json_response(
            {
                "ok": False,
                "service": "777MAZ bot",
                "error": repr(e)
            },
            status=500
        )


async def ensure_webhook():
    base = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if not base:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL topilmadi"
        )

    secret = os.environ.get(
        "WEBHOOK_SECRET",
        "777maz-secret"
    )

    url = (
        f"{base.rstrip('/')}/webhook/{secret}"
    )

    allowed = dp.resolve_used_update_types()

    try:
        info = await bot.get_webhook_info()

        print(
            "Webhook check:",
            "url=", info.url,
            "pending=", info.pending_update_count,
            "last_error=", info.last_error_message
        )

        if info.url != url:
            print(
                "Webhook missing/wrong. Setting again:",
                url
            )

            await bot.set_webhook(
                url,
                drop_pending_updates=False,
                allowed_updates=allowed
            )

            info = await bot.get_webhook_info()

            print(
                "Webhook repaired:",
                "url=", info.url,
                "pending=", info.pending_update_count,
                "last_error=", info.last_error_message
            )

    except Exception as e:
        print(
            "Webhook ensure error:",
            repr(e)
        )
        raise

    return url


# =========================
# SUPABASE PRODUCT SYNC
# =========================

async def sync_products():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        print(
            "Supabase sync skipped: env yo‘q"
        )
        return

    try:
        con = db()

        local_rows = con.execute(
            """SELECT id,name,price,category,image_file_id,
                      old_price,is_discount,is_new
               FROM products
               ORDER BY id"""
        ).fetchall()

        con.close()

        remote = await supabase_request(
            "GET",
            "products?select=id,name,price,category,image_file_id,old_price,is_discount,is_new&order=id"
        ) or []

        remote_ids = {
            int(r["id"])
            for r in remote
            if r.get("id") is not None
        }

        missing = []

        for r in local_rows:
            if r[0] not in remote_ids:
                missing.append({
                    "id": r[0],
                    "name": r[1],
                    "price": r[2],
                    "category": r[3] or "",
                    "image_file_id": r[4] or "",
                    "old_price": r[5] or 0,
                    "is_discount": bool(r[6]),
                    "is_new": bool(r[7])
                })

        if missing:
            await supabase_request(
                "POST",
                "products?on_conflict=id",
                missing
            )

            print(
                f"SQLite -> Supabase: "
                f"{len(missing)} ta yangi mahsulot"
            )

        # Supabase -> SQLite
        if remote:
            con = db()

            for r in remote:
                con.execute(
                    """INSERT INTO products(
                       id,name,price,category,image_file_id,
                       old_price,is_discount,is_new)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name,
                       price=excluded.price,
                       category=excluded.category,
                       image_file_id=excluded.image_file_id,
                       old_price=excluded.old_price,
                       is_discount=excluded.is_discount,
                       is_new=excluded.is_new""",
                    (
                        r.get("id"),
                        r.get("name", ""),
                        int(r.get("price", 0)),
                        r.get("category", ""),
                        r.get("image_file_id", ""),
                        int(r.get("old_price", 0) or 0),
                        int(bool(r.get("is_discount"))),
                        int(bool(r.get("is_new")))
                    )
                )

            con.commit()
            con.close()

        print(
            f"Web Market sync OK: "
            f"local={len(local_rows)}, "
            f"remote={len(remote)}"
        )

    except Exception as e:
        print(
            "Supabase sync error:",
            repr(e)
        )


# =========================
# APP STARTUP
# =========================

async def on_startup(app):
    init_db()

    print(
        "ADMIN_ID:",
        repr(ADMIN_ID)
    )

    print(
        "PRIMARY_ADMIN_ID:",
        PRIMARY_ADMIN_ID
    )

    seed_products()

    await sync_products()

    await ensure_webhook()

    print(
        "Web Market products sync completed"
    )


async def on_cleanup(app):
    try:
        await bot.session.close()
    except Exception:
        pass


def create_app():
    app = web.Application()

    secret = os.environ.get(
        "WEBHOOK_SECRET",
        "777maz-secret"
    )

    app.router.add_get(
        "/",
        web_index
    )

    app.router.add_get(
        "/health",
        health
    )

    app.router.add_get(
        "/api/products",
        api_products
    )

    app.router.add_get(
        "/api/product-image",
        api_product_image
    )

    app.router.add_get(
        "/api/settings",
        api_settings
    )

    app.router.add_post(
        "/api/order",
        api_order
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
