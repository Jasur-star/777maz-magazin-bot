import os
import sqlite3
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
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
ADMIN_ID = os.getenv("ADMIN_ID", "8082110485")

# KATALOG KATEGORIYALARI
CATEGORIES = [
    ("🥤", "Ichimliklar"),
    ("🍫", "Shirinliklar"),
    ("🍎", "Mevalar"),
    ("🥕", "Sabzavotlar"),
    ("👶", "Bolalar ovqati"),
    ("🍳", "Oshxona mahsulotlari"),
    ("🧴", "Gellar va shampunlar"),
]


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
            price INTEGER NOT NULL,
            category TEXT DEFAULT 'Oshxona mahsulotlari',
            photo_id TEXT
        )
    """)

    # Eski shop.db bo'lsa, category ustunini qo'shamiz
    cur.execute("PRAGMA table_info(products)")
    columns = [row[1] for row in cur.fetchall()]

    if "category" not in columns:
        cur.execute(
            "ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'Oshxona mahsulotlari'"
        )

    if "photo_id" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN photo_id TEXT")

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
    """
    Birinchi marta baza bo'sh bo'lsa, vaqtinchalik namunaviy mahsulotlar qo'shiladi.
    Keyinchalik ularni o'zgartirish yoki ko'paytirish mumkin.
    """
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    count = cur.fetchone()[0]

    if count == 0:
        products = [
            ("Sut 1 litr", 10000, "Ichimliklar"),
            ("Choy", 18000, "Ichimliklar"),
            ("Shakar 1 kg", 12000, "Shirinliklar"),
            ("Non", 5000, "Oshxona mahsulotlari"),
        ]

        cur.executemany(
            """
            INSERT INTO products (name, price, category)
            VALUES (?, ?, ?)
            """,
            products
        )

    db.commit()
    db.close()


# =========================
# KLAVIATURALAR
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


def catalog_keyboard():
    buttons = []

    for emoji, name in CATEGORIES:
        buttons.append([
            InlineKeyboardButton(
                text=f"{emoji} {name}",
                callback_data=f"category:{name}"
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


def products_keyboard(category):
    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT id, name, price
        FROM products
        WHERE category = ?
        ORDER BY id
        """,
        (category,)
    )

    products = cur.fetchall()
    db.close()

    buttons = []

    for product_id, name, price in products:
        buttons.append([
            InlineKeyboardButton(
                text=f"{name} — {price:,} so'm",
                callback_data=f"product:{product_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Kategoriyalar",
            callback_data="products"
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
admin_states = {}


# =========================
# ADMIN PANEL
# =========================

def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID) and str(user_id) == str(ADMIN_ID)


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Mahsulot qo‘shish", callback_data="admin_add")],
        [InlineKeyboardButton(text="📋 Mahsulotlar ro‘yxati", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Mahsulot o‘chirish", callback_data="admin_delete")],
    ])


def admin_category_keyboard():
    rows = []
    for emoji, name in CATEGORIES:
        rows.append([
            InlineKeyboardButton(
                text=f"{emoji} {name}",
                callback_data=f"admin_cat:{name}"
            )
        ])
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not ADMIN_ID:
        await message.answer(
            "⚠️ Admin ID sozlanmagan. Render → Environment → ADMIN_ID ga Telegram ID ni kiriting."
        )
        return

    if not is_admin(message.from_user.id):
        await message.answer("⛔ Sizda admin huquqi yo‘q.")
        return
    await message.answer(
        "⚙️ ADMIN PANEL\n\nKerakli amalni tanlang:",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    admin_states[callback.from_user.id] = {"step": "name"}
    await callback.message.answer("➕ Yangi mahsulot nomini yozing:")
    await callback.answer()


@dp.callback_query(F.data == "admin_list")
async def admin_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, name, price, category, photo_id FROM products ORDER BY id DESC")
    products = cur.fetchall()
    db.close()
    if not products:
        text = "📋 Hozircha mahsulotlar yo‘q."
    else:
        text = "📋 MAHSULOTLAR\n\n"
        for pid, name, price, category, photo_id in products:
            photo_mark = "📷" if photo_id else "🖼️ yo‘q"
            text += f"#{pid} • {name} — {price:,} so‘m\n   {category} • {photo_mark}\n\n"
    await callback.message.answer(text, reply_markup=admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_delete")
async def admin_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, name, price FROM products ORDER BY id DESC")
    products = cur.fetchall()
    db.close()
    if not products:
        await callback.answer("Mahsulotlar yo‘q", show_alert=True)
        return
    buttons = []
    for pid, name, price in products:
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 {name} — {price:,} so‘m",
                callback_data=f"admin_del:{pid}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin_panel")])
    await callback.message.answer(
        "🗑 O‘chirmoqchi bo‘lgan mahsulotni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_del:"))
async def admin_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    product_id = int(callback.data.split(":", 1)[1])
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT name FROM products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    if not row:
        db.close()
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    name = row[0]
    cur.execute("DELETE FROM cart WHERE product_id = ?", (product_id,))
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    db.close()
    await callback.message.answer(f"✅ {name} o‘chirildi.", reply_markup=admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_cat:"))
async def admin_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    user_id = callback.from_user.id
    state = admin_states.get(user_id)

    if not state or state.get("step") != "category":
        await callback.answer(
            "Mahsulot qo‘shish jarayoni topilmadi",
            show_alert=True
        )
        return

    category = callback.data.split(":", 1)[1]
    state["category"] = category
    state["step"] = "photo"

    await callback.message.answer(
        "📷 Endi mahsulot rasmini yuboring.\n\n"
        "Rasmni oddiy foto sifatida yuboring."
    )
    await callback.answer()


@dp.message(F.photo)
async def admin_product_photo(message: Message):
    user_id = message.from_user.id

    if not is_admin(user_id) or user_id not in admin_states:
        return

    state = admin_states[user_id]

    if state.get("step") != "photo":
        return

    state["photo_id"] = message.photo[-1].file_id

    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        INSERT INTO products (name, price, category, photo_id)
        VALUES (?, ?, ?, ?)
        """,
        (
            state["name"],
            state["price"],
            state["category"],
            state["photo_id"]
        )
    )
    db.commit()
    db.close()

    await message.answer_photo(
        state["photo_id"],
        caption=(
            "✅ Mahsulot qo‘shildi!\n\n"
            f"🛍 {state['name']}\n"
            f"💰 {state['price']:,} so‘m\n"
            f"📂 {state['category']}"
        )
    )

    admin_states.pop(user_id, None)
    await message.answer(
        "⚙️ Admin panel:",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    await callback.message.answer("⚙️ ADMIN PANEL", reply_markup=admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return
    admin_states.pop(callback.from_user.id, None)
    await callback.message.answer("❌ Bekor qilindi.", reply_markup=admin_keyboard())
    await callback.answer()


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
# MAHSULOTLAR / KATALOG
# =========================

@dp.callback_query(F.data == "products")
async def products_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍 MAHSULOTLAR KATALOGI\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=catalog_keyboard()
    )
    await callback.answer()


# =========================
# KATEGORIYA ICHIGA KIRISH
# =========================

@dp.callback_query(F.data.startswith("category:"))
async def category_callback(callback: CallbackQuery):
    category = callback.data.split(":", 1)[1]

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM products WHERE category = ?",
        (category,)
    )
    count = cur.fetchone()[0]
    db.close()

    if count == 0:
        text = (
            f"{category}\n\n"
            "📭 Bu bo‘limda hozircha mahsulotlar yo‘q."
        )
    else:
        text = (
            f"{category}\n\n"
            "Mahsulotni tanlang:"
        )

    await callback.message.edit_text(
        text,
        reply_markup=products_keyboard(category)
    )
    await callback.answer()


# =========================
# MAHSULOT RASMI / MA'LUMOTI
# =========================

@dp.callback_query(F.data.startswith("product:"))
async def product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split(":", 1)[1])

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT name, price, category, photo_id FROM products WHERE id = ?",
        (product_id,)
    )
    product = cur.fetchone()
    db.close()

    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return

    name, price, category, photo_id = product
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Savatga qo‘shish", callback_data=f"add_to_cart:{product_id}")],
        [InlineKeyboardButton(text="⬅️ Kategoriyaga qaytish", callback_data=f"category:{category}")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
    ])

    caption = (
        f"🛍 {name}\n\n"
        f"💰 Narxi: {price:,} so‘m\n"
        f"📂 {category}"
    )

    try:
        if photo_id:
            await callback.message.answer_photo(
                photo_id,
                caption=caption,
                reply_markup=keyboard
            )
        else:
            await callback.message.answer(
                caption + "\n\n📷 Rasm hozircha mavjud emas.",
                reply_markup=keyboard
            )
    except Exception as e:
        print("Mahsulot rasmi yuborilmadi:", e)
        await callback.message.answer(caption, reply_markup=keyboard)

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
        "SELECT name, price, photo_id FROM products WHERE id = ?",
        (product_id,)
    )

    product = cur.fetchone()

    if not product:
        db.close()
        await callback.answer(
            "Mahsulot topilmadi",
            show_alert=True
        )
        return

    name, price, photo_id = product

    cur.execute(
        """
        SELECT quantity
        FROM cart
        WHERE user_id = ? AND product_id = ?
        """,
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

    # ADMIN MAHSULOT QO‘SHISH JARAYONI
    if is_admin(user_id) and user_id in admin_states:
        state = admin_states[user_id]
        text = (message.text or "").strip()
        if state["step"] == "name":
            if len(text) < 2:
                await message.answer("Mahsulot nomini to‘liqroq yozing:")
                return
            state["name"] = text
            state["step"] = "price"
            await message.answer("💰 Mahsulot narxini faqat raqamda yozing. Masalan: 15000")
            return
        if state["step"] == "price":
            price_text = text.replace(" ", "").replace(",", "")
            if not price_text.isdigit() or int(price_text) <= 0:
                await message.answer("❗ Narxni faqat raqamda yozing. Masalan: 15000")
                return
            state["price"] = int(price_text)
            state["step"] = "category"
            await message.answer("📂 Kategoriyani tanlang:", reply_markup=admin_category_keyboard())
            return
        if state["step"] == "category":
            await message.answer("📂 Iltimos, pastdagi kategoriyalardan birini tanlang.", reply_markup=admin_category_keyboard())
            return

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
                f"  {summa:,} so‘m\n"
            )

        state["items"] = items_text
        state["total"] = total

        await message.answer(
            "📋 BUYURTMA MA'LUMOTLARI\n\n"
            f"👤 Ism: {state['name']}\n"
            f"📞 Telefon: {state['phone']}\n"
            f"📍 Manzil: {state['address']}\n\n"
            f"🛍 Mahsulotlar:\n{items_text}\n"
            f"💰 Jami: {total:,} so‘m\n\n"
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

    cur.execute(
        "DELETE FROM cart WHERE user_id = ?",
        (user_id,)
    )

    db.commit()
    db.close()

    order_states.pop(user_id, None)

    await callback.message.answer(
        "✅ BUYURTMANGIZ QABUL QILINDI!\n\n"
        f"📦 Buyurtma №{order_id}\n"
        f"💰 Jami: {state['total']:,} so‘m\n\n"
        "Tez orada siz bilan bog‘lanamiz.",
        reply_markup=main_menu()
    )

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
                f"💰 Jami: {state['total']:,} so‘m\n\n"
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
            f"💰 {total:,} so‘m\n"
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

    print(f"Webhook set: {webhook_url}")


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

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

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
