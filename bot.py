import os
import sqlite3
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

bot = Bot(TOKEN)
dp = Dispatcher()

DB_NAME = "shop.db"
ADMIN_ID = os.getenv("ADMIN_ID")
CONTACT_PHONE = os.getenv("CONTACT_PHONE", "+998 99 690 24 07")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "").strip()
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "").strip()

CATEGORIES = [
    "🥤 Ichimliklar",
    "🍫 Shirinliklar",
    "🍎 Mevalar",
    "🥕 Sabzavotlar",
    "👶 Bolalar ovqati",
    "🍳 Oshxona mahsulotlari",
    "🧴 Gellar va shampunlar",
]

order_states = {}
admin_states = {}
profile_states = {}
search_states = set()


def get_db():
    return sqlite3.connect(DB_NAME)


def add_column(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT DEFAULT '🍳 Oshxona mahsulotlari',
            image_file_id TEXT,
            old_price INTEGER DEFAULT 0,
            is_discount INTEGER DEFAULT 0,
            is_new INTEGER DEFAULT 0
        )
    """)
    add_column(cur, "products", "category", "TEXT DEFAULT '🍳 Oshxona mahsulotlari'")
    add_column(cur, "products", "image_file_id", "TEXT")
    add_column(cur, "products", "old_price", "INTEGER DEFAULT 0")
    add_column(cur, "products", "is_discount", "INTEGER DEFAULT 0")
    add_column(cur, "products", "is_new", "INTEGER DEFAULT 0")

    # Eski bazadagi emoji-siz kategoriyalarni yangi nomlarga moslaymiz.
    category_map = {
        "Ichimliklar": "🥤 Ichimliklar",
        "Shirinliklar": "🍫 Shirinliklar",
        "Mevalar": "🍎 Mevalar",
        "Sabzavotlar": "🥕 Sabzavotlar",
        "Bolalar ovqati": "👶 Bolalar ovqati",
        "Oshxona mahsulotlari": "🍳 Oshxona mahsulotlari",
        "Gellar va shampunlar": "🧴 Gellar va shampunlar",
    }
    for old_cat, new_cat in category_map.items():
        cur.execute("UPDATE products SET category=? WHERE category=?", (new_cat, old_cat))

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
            created_at TEXT NOT NULL,
            payment_method TEXT DEFAULT 'Naqd'
        )
    """)
    add_column(cur, "orders", "payment_method", "TEXT DEFAULT 'Naqd'")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    db.commit()
    db.close()


def seed_products():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        products = [
            ("Sut 1 litr", 10000, "🥤 Ichimliklar", None, 0, 0, 0),
            ("Choy", 18000, "🥤 Ichimliklar", None, 0, 0, 0),
            ("Shakar 1 kg", 12000, "🍫 Shirinliklar", None, 0, 0, 0),
            ("Non", 5000, "🍳 Oshxona mahsulotlari", None, 0, 0, 0),
        ]
        cur.executemany("""
            INSERT INTO products
            (name, price, category, image_file_id, old_price, is_discount, is_new)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, products)
    db.commit()
    db.close()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Mahsulotlar", callback_data="products")],
        [InlineKeyboardButton(text="🏷️ Chegirma tovarlar", callback_data="discounts"),
         InlineKeyboardButton(text="🆕 Yangi mahsulotlar", callback_data="new_products")],
        [InlineKeyboardButton(text="🛒 Savat", callback_data="cart"),
         InlineKeyboardButton(text="📝 Buyurtma berish", callback_data="order")],
        [InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="orders"),
         InlineKeyboardButton(text="💳 To‘lov usuli", callback_data="payment_info")],
        [InlineKeyboardButton(text="👤 Profilim", callback_data="profile"),
         InlineKeyboardButton(text="⭐ Sevimlilar", callback_data="favorites")],
        [InlineKeyboardButton(text="🔎 Qidirish", callback_data="search")],
        [InlineKeyboardButton(text="📞 Aloqa", callback_data="contact")],
    ])


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")]
    ])


def catalog_keyboard():
    buttons = [[InlineKeyboardButton(text=c, callback_data=f"category:{i}")] for i, c in enumerate(CATEGORIES)]
    buttons += [
        [InlineKeyboardButton(text="🛒 Savat", callback_data="cart")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def products_keyboard_for_rows(rows, back_callback="products"):
    buttons = []
    for pid, name, price, old_price, is_discount, is_new in rows:
        label = f"{name} — {price:,} so'm"
        if is_discount and old_price:
            label = f"🏷️ {name} — {price:,} so'm"
        elif is_new:
            label = f"🆕 {name} — {price:,} so'm"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"product:{pid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)])
    buttons.append([InlineKeyboardButton(text="🛒 Savat", callback_data="cart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def products_keyboard(category_index):
    category = CATEGORIES[category_index]
    db = get_db(); cur = db.cursor()
    cur.execute("""
        SELECT id, name, price, old_price, is_discount, is_new
        FROM products WHERE category = ? ORDER BY id
    """, (category,))
    rows = cur.fetchall(); db.close()
    return products_keyboard_for_rows(rows, "products")


def payment_methods_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Karta orqali", callback_data="pay:card")],
        [InlineKeyboardButton(text="💵 Naqd pul", callback_data="pay:cash")],
        [InlineKeyboardButton(text="🏪 Joyida to‘lov", callback_data="pay:onsite")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order")],
    ])


def confirm_order_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Buyurtmani tasdiqlash", callback_data="confirm_order")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order")],
    ])


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Telefon raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Mahsulot qo‘shish", callback_data="admin_add")],
        [InlineKeyboardButton(text="🏷️ Chegirmaga mahsulot qo‘shish", callback_data="admin_add_discount")],
        [InlineKeyboardButton(text="🆕 Yangi mahsulot qo‘shish", callback_data="admin_add_new")],
        [InlineKeyboardButton(text="📋 Mahsulotlar ro‘yxati", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Mahsulot o‘chirish", callback_data="admin_delete")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")],
    ])


def admin_category_keyboard():
    buttons = [[InlineKeyboardButton(text=c, callback_data=f"admin_cat:{i}")] for i, c in enumerate(CATEGORIES)]
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_section_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Oddiy mahsulot", callback_data="admin_section:normal")],
        [InlineKeyboardButton(text="🏷️ Chegirma tovar", callback_data="admin_section:discount")],
        [InlineKeyboardButton(text="🆕 Yangi mahsulot", callback_data="admin_section:new")],
        [InlineKeyboardButton(text="🏷️🆕 Ikkalasiga ham", callback_data="admin_section:both")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel")],
    ])


def admin_delete_keyboard():
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT id, name, price FROM products ORDER BY id DESC")
    rows = cur.fetchall(); db.close()
    buttons = [[InlineKeyboardButton(text=f"🗑 {name} — {price:,} so'm", callback_data=f"admin_del:{pid}")] for pid, name, price in rows]
    buttons.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_admin(user_id):
    return ADMIN_ID and str(user_id) == str(ADMIN_ID)


def profile_get(user_id):
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT name, phone, address FROM profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone(); db.close()
    return row or ("", "", "")


def profile_save(user_id, name=None, phone=None, address=None):
    old_name, old_phone, old_address = profile_get(user_id)
    db = get_db(); cur = db.cursor()
    cur.execute("""
        INSERT INTO profiles(user_id, name, phone, address) VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, phone=excluded.phone, address=excluded.address
    """, (user_id, name if name is not None else old_name,
          phone if phone is not None else old_phone,
          address if address is not None else old_address))
    db.commit(); db.close()


def favorites_keyboard(user_id):
    db = get_db(); cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.price, p.old_price, p.is_discount, p.is_new
        FROM favorites f JOIN products p ON p.id=f.product_id
        WHERE f.user_id=? ORDER BY p.id DESC
    """, (user_id,))
    rows = cur.fetchall(); db.close()
    buttons = [[InlineKeyboardButton(text=f"⭐ {name} — {price:,} so'm", callback_data=f"product:{pid}")] for pid,name,price,old_price,is_discount,is_new in rows]
    buttons.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🛍 Assalomu alaykum!\n\n777MAZ Magazin botiga xush kelibsiz!\n\nKerakli bo‘limni tanlang:",
        reply_markup=main_menu(),
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Sizda admin huquqi yo‘q.")
        return
    admin_states.pop(message.from_user.id, None)
    await message.answer("⚙️ ADMIN PANEL\n\nKerakli amalni tanlang:", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "admin")
async def admin_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    admin_states.pop(callback.from_user.id, None)
    await callback.message.edit_text("⚙️ ADMIN PANEL\n\nKerakli amalni tanlang:", reply_markup=admin_keyboard())
    await callback.answer()


async def start_admin_add(callback, mode="normal"):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    admin_states[callback.from_user.id] = {"step":"name", "name":"", "price":0, "old_price":0,
                                           "category":"", "is_discount":1 if mode=="discount" else 0,
                                           "is_new":1 if mode=="new" else 0,
                                           "forced_mode":mode}
    await callback.message.answer("➕ MAHSULOT QO‘SHISH\n\n1️⃣ Mahsulot nomini yozing:")
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add(callback):
    await start_admin_add(callback, "normal")


@dp.callback_query(F.data == "admin_add_discount")
async def admin_add_discount(callback):
    await start_admin_add(callback, "discount")


@dp.callback_query(F.data == "admin_add_new")
async def admin_add_new(callback):
    await start_admin_add(callback, "new")


@dp.callback_query(F.data.startswith("admin_cat:"))
async def admin_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    state = admin_states.get(callback.from_user.id)
    if not state or state.get("step") != "category":
        await callback.answer("Avval mahsulot qo‘shishni boshlang.", show_alert=True); return
    index = int(callback.data.split(":")[1])
    state["category"] = CATEGORIES[index]
    state["step"] = "section" if state.get("forced_mode") == "normal" else ("old_price" if state.get("forced_mode") == "discount" else "photo")
    if state["step"] == "section":
        await callback.message.answer("4️⃣ Mahsulot qaysi bo‘limda ko‘rinsin?", reply_markup=admin_section_keyboard())
    elif state["step"] == "old_price":
        await callback.message.answer("4️⃣ Eski narxni yozing (masalan: 12000):")
    else:
        await callback.message.answer("4️⃣ Endi mahsulot rasmini yuboring 📷\n\nRasm yuborish majburiy.")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_section:"))
async def admin_section(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    state = admin_states.get(callback.from_user.id)
    if not state or state.get("step") != "section":
        await callback.answer("Jarayon topilmadi.", show_alert=True); return
    mode = callback.data.split(":")[1]
    state["is_discount"] = 1 if mode in ("discount", "both") else 0
    state["is_new"] = 1 if mode in ("new", "both") else 0
    if state["is_discount"]:
        state["step"] = "old_price"
        await callback.message.answer("5️⃣ Eski narxni yozing (masalan: 12000):")
    else:
        state["step"] = "photo"
        await callback.message.answer("5️⃣ Endi mahsulot rasmini yuboring 📷")
    await callback.answer()


@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    admin_states.pop(callback.from_user.id, None)
    await callback.message.answer("❌ Amal bekor qilindi.", reply_markup=admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_list")
async def admin_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT id,name,price,category,old_price,is_discount,is_new,image_file_id FROM products ORDER BY id DESC")
    rows = cur.fetchall(); db.close()
    if not rows:
        await callback.message.edit_text("📋 Hozircha mahsulotlar yo‘q.", reply_markup=admin_keyboard()); await callback.answer(); return
    text = "📋 MAHSULOTLAR RO‘YXATI\n\n"
    for pid,name,price,cat,old,disc,new,img in rows:
        flags = (" 🏷️" if disc else "") + (" 🆕" if new else "")
        text += f"№{pid} — {name}{flags}\n💰 {price:,} so‘m" + (f" (eski {old:,})" if disc and old else "") + f"\n📂 {cat}\n\n"
    await callback.message.edit_text(text[:3900], reply_markup=admin_keyboard()); await callback.answer()


@dp.callback_query(F.data == "admin_delete")
async def admin_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    await callback.message.edit_text("🗑 O‘CHIRILADIGAN MAHSULOTNI TANLANG:", reply_markup=admin_delete_keyboard()); await callback.answer()


@dp.callback_query(F.data.startswith("admin_del:"))
async def admin_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Admin huquqi yo‘q.", show_alert=True); return
    pid = int(callback.data.split(":")[1])
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT name FROM products WHERE id=?", (pid,)); row = cur.fetchone()
    if not row:
        db.close(); await callback.answer("Mahsulot topilmadi", show_alert=True); return
    cur.execute("DELETE FROM cart WHERE product_id=?", (pid,))
    cur.execute("DELETE FROM favorites WHERE product_id=?", (pid,))
    cur.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit(); db.close()
    await callback.answer(f"✅ {row[0]} o‘chirildi", show_alert=True)
    await callback.message.edit_text("🗑 O‘CHIRILADIGAN MAHSULOTNI TANLANG:", reply_markup=admin_delete_keyboard())


@dp.message(F.photo)
async def photo_received(message: Message):
    uid = message.from_user.id
    if not is_admin(uid): return
    state = admin_states.get(uid)
    if not state or state.get("step") != "photo": return
    photo = message.photo[-1]
    db = get_db(); cur = db.cursor()
    cur.execute("""
        INSERT INTO products(name,price,category,image_file_id,old_price,is_discount,is_new)
        VALUES(?,?,?,?,?,?,?)
    """, (state["name"],state["price"],state["category"],photo.file_id,state.get("old_price",0),state.get("is_discount",0),state.get("is_new",0)))
    pid = cur.lastrowid; db.commit(); db.close()
    admin_states.pop(uid, None)
    flags = ("🏷️ Chegirma\n" if state.get("is_discount") else "") + ("🆕 Yangi\n" if state.get("is_new") else "")
    await message.answer(f"✅ MAHSULOT QO‘SHILDI!\n\n🆔 ID: {pid}\n🛍 {state['name']}\n💰 {state['price']:,} so‘m\n{flags}📂 {state['category']}\n🖼 Rasm saqlandi", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "products")
async def products_callback(callback: CallbackQuery):
    await callback.message.edit_text("🛍 MAHSULOTLAR KATALOGI\n\nKerakli kategoriyani tanlang:", reply_markup=catalog_keyboard()); await callback.answer()


@dp.callback_query(F.data.startswith("category:"))
async def category_callback(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    if index < 0 or index >= len(CATEGORIES):
        await callback.answer("Kategoriya topilmadi", show_alert=True); return
    await callback.message.edit_text(f"{CATEGORIES[index]}\n\nMahsulotni tanlang:", reply_markup=products_keyboard(index)); await callback.answer()


async def show_product(callback: CallbackQuery, pid: int):
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT name,price,category,image_file_id,old_price,is_discount,is_new FROM products WHERE id=?", (pid,))
    p = cur.fetchone(); db.close()
    if not p:
        await callback.answer("Mahsulot topilmadi", show_alert=True); return
    name,price,category,img,old_price,is_discount,is_new = p
    user_id = callback.from_user.id
    db=get_db(); cur=db.cursor(); cur.execute("SELECT 1 FROM favorites WHERE user_id=? AND product_id=?",(user_id,pid)); fav=cur.fetchone() is not None; db.close()
    try: cat_idx=CATEGORIES.index(category)
    except ValueError: cat_idx=0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛒 Savatga qo‘shish — {price:,} so'm", callback_data=f"add_to_cart:{pid}")],
        [InlineKeyboardButton(text=("💔 Sevimlilardan olib tashlash" if fav else "⭐ Sevimlilarga qo‘shish"), callback_data=f"fav:{pid}")],
        [InlineKeyboardButton(text="⬅️ Mahsulotlar", callback_data=f"category:{cat_idx}")],
        [InlineKeyboardButton(text="🛒 Savat", callback_data="cart")],
    ])
    flags = (f"🏷️ Eski narx: {old_price:,} so'm\n" if is_discount and old_price else "") + ("🆕 Yangi mahsulot\n" if is_new else "")
    text=f"🛍 {name}\n\n{flags}💰 Narxi: {price:,} so'm\n📂 {category}\n\nSavatga qo‘shish yoki sevimliga saqlash mumkin."
    if img: await callback.message.answer_photo(photo=img, caption=text, reply_markup=kb)
    else: await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("product:"))
async def product_callback(callback: CallbackQuery):
    await show_product(callback, int(callback.data.split(":")[1]))


@dp.callback_query(F.data.startswith("fav:"))
async def favorite_toggle(callback: CallbackQuery):
    pid=int(callback.data.split(":")[1]); uid=callback.from_user.id
    db=get_db(); cur=db.cursor(); cur.execute("SELECT 1 FROM products WHERE id=?",(pid,))
    if not cur.fetchone(): db.close(); await callback.answer("Mahsulot topilmadi",show_alert=True); return
    cur.execute("SELECT 1 FROM favorites WHERE user_id=? AND product_id=?",(uid,pid))
    if cur.fetchone():
        cur.execute("DELETE FROM favorites WHERE user_id=? AND product_id=?",(uid,pid)); msg="💔 Sevimlilardan olib tashlandi"
    else:
        cur.execute("INSERT INTO favorites(user_id,product_id) VALUES(?,?)",(uid,pid)); msg="⭐ Sevimlilarga qo‘shildi"
    db.commit(); db.close(); await callback.answer(msg)


@dp.callback_query(F.data == "favorites")
async def favorites_callback(callback: CallbackQuery):
    uid=callback.from_user.id
    db=get_db(); cur=db.cursor(); cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?",(uid,)); count=cur.fetchone()[0]; db.close()
    if not count:
        await callback.message.edit_text("⭐ Sevimlilar\n\nHozircha sevimli mahsulotlaringiz yo‘q.", reply_markup=back_home())
    else:
        await callback.message.edit_text("⭐ SEVIMLI MAHSULOTLAR\n\nKerakli mahsulotni tanlang:", reply_markup=favorites_keyboard(uid))
    await callback.answer()


async def featured_list(callback, kind):
    field = "is_discount" if kind == "discount" else "is_new"
    title = "🏷️ CHEGIRMA TOVARLAR" if kind == "discount" else "🆕 YANGI MAHSULOTLAR"
    db=get_db(); cur=db.cursor(); cur.execute(f"SELECT id,name,price,old_price,is_discount,is_new FROM products WHERE {field}=1 ORDER BY id DESC")
    rows=cur.fetchall(); db.close()
    if not rows:
        await callback.message.edit_text(f"{title}\n\nHozircha mahsulot yo‘q.", reply_markup=back_home())
    else:
        await callback.message.edit_text(f"{title}\n\nMahsulotni tanlang:", reply_markup=products_keyboard_for_rows(rows, "home"))
    await callback.answer()


@dp.callback_query(F.data == "discounts")
async def discounts_callback(callback): await featured_list(callback, "discount")

@dp.callback_query(F.data == "new_products")
async def new_products_callback(callback): await featured_list(callback, "new")


@dp.callback_query(F.data.startswith("add_to_cart:"))
async def add_to_cart(callback: CallbackQuery):
    pid=int(callback.data.split(":")[1]); uid=callback.from_user.id
    db=get_db(); cur=db.cursor(); cur.execute("SELECT name FROM products WHERE id=?",(pid,)); p=cur.fetchone()
    if not p: db.close(); await callback.answer("Mahsulot topilmadi",show_alert=True); return
    cur.execute("SELECT quantity FROM cart WHERE user_id=? AND product_id=?",(uid,pid))
    if cur.fetchone(): cur.execute("UPDATE cart SET quantity=quantity+1 WHERE user_id=? AND product_id=?",(uid,pid))
    else: cur.execute("INSERT INTO cart(user_id,product_id,quantity) VALUES(?,?,1)",(uid,pid))
    db.commit(); db.close(); await callback.answer(f"✅ {p[0]} savatga qo‘shildi")


@dp.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    uid=callback.from_user.id; db=get_db(); cur=db.cursor()
    cur.execute("SELECT products.name,products.price,cart.quantity FROM cart JOIN products ON products.id=cart.product_id WHERE cart.user_id=?",(uid,)); items=cur.fetchall(); db.close()
    if not items:
        await callback.message.edit_text("🛒 Savatingiz hozircha bo‘sh.", reply_markup=back_home()); await callback.answer(); return
    total=sum(p*q for _,p,q in items); text="🛒 SIZNING SAVATINGIZ\n\n"
    for name,price,q in items: text += f"• {name}\n  {q} dona × {price:,} so'm = {price*q:,} so'm\n\n"
    text += f"💰 Jami: {total:,} so'm"
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Buyurtma berish",callback_data="order")],
        [InlineKeyboardButton(text="🛍 Yana mahsulot olish",callback_data="products")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",callback_data="home")],
    ])
    await callback.message.edit_text(text,reply_markup=kb); await callback.answer()


@dp.callback_query(F.data == "order")
async def order_callback(callback: CallbackQuery):
    uid=callback.from_user.id; db=get_db(); cur=db.cursor(); cur.execute("SELECT COUNT(*) FROM cart WHERE user_id=?",(uid,)); count=cur.fetchone()[0]; db.close()
    if not count: await callback.answer("Avval mahsulotlarni savatga qo‘shing 🛒",show_alert=True); return
    name,phone,address=profile_get(uid)
    order_states[uid]={"step":"name","name":name,"phone":phone,"address":address}
    if not name:
        await callback.message.answer("📝 BUYURTMA BERISH\n\n1️⃣ Ismingizni yozing:");
    elif not phone:
        order_states[uid]["step"]="phone"; await callback.message.answer("📞 Telefon raqamingizni yuboring:",reply_markup=phone_keyboard())
    elif not address:
        order_states[uid]["step"]="address"; await callback.message.answer("📍 Yetkazib berish manzilingizni yozing:")
    else:
        order_states[uid]["step"]="payment"; await callback.message.answer("💳 To‘lov usulini tanlang:",reply_markup=payment_methods_keyboard())
    await callback.answer()


async def finish_order_preview(user_id, message):
    state=order_states[user_id]; db=get_db(); cur=db.cursor()
    cur.execute("SELECT products.name,products.price,cart.quantity FROM cart JOIN products ON products.id=cart.product_id WHERE cart.user_id=?",(user_id,)); items=cur.fetchall(); db.close()
    if not items:
        order_states.pop(user_id,None); await message.answer("🛒 Savatingiz bo‘sh.",reply_markup=main_menu()); return
    total=sum(p*q for _,p,q in items); items_text="".join(f"• {n} — {q} dona\n  {p*q:,} so'm\n" for n,p,q in items)
    state["items"]=items_text; state["total"]=total
    await message.answer("📋 BUYURTMA MA'LUMOTLARI\n\n"
        f"👤 Ism: {state['name']}\n📞 Telefon: {state['phone']}\n📍 Manzil: {state['address']}\n"
        f"💳 To‘lov: {state.get('payment_method','')}\n\n🛍 Mahsulotlar:\n{items_text}\n💰 Jami: {total:,} so'm\n\nBuyurtmani tasdiqlaysizmi?",
        reply_markup=confirm_order_keyboard())


@dp.callback_query(F.data.startswith("pay:"))
async def payment_selected(callback: CallbackQuery):
    uid=callback.from_user.id
    if uid not in order_states: await callback.answer("Avval buyurtma boshlang.",show_alert=True); return
    method=callback.data.split(":")[1]
    labels={"card":"💳 Karta orqali","cash":"💵 Naqd pul","onsite":"🏪 Joyida to‘lov"}
    order_states[uid]["payment_method"]=labels[method]
    if method=="card":
        if CARD_NUMBER:
            holder=f"\n👤 Karta egasi: {CARD_HOLDER}" if CARD_HOLDER else ""
            await callback.message.answer(f"💳 Karta orqali to‘lov\n\n💳 Karta: {CARD_NUMBER}{holder}\n\nTo‘lovni amalga oshirgach, buyurtmani tasdiqlang.")
        else:
            await callback.message.answer("💳 Karta orqali to‘lov uchun karta/Click/Payme ma’lumotlari hali ulanmagan. Hozircha buyurtma qabul qilinadi, to‘lovni admin bilan aniqlashtirasiz.")
    await finish_order_preview(uid, callback.message)
    await callback.answer()


@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery):
    uid=callback.from_user.id
    if uid not in order_states: await callback.answer("Buyurtma ma’lumotlari topilmadi.",show_alert=True); return
    state=order_states[uid]
    if not state.get("payment_method"):
        await callback.answer("To‘lov usulini tanlang.",show_alert=True); return
    db=get_db(); cur=db.cursor(); created=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    profile_save(uid,state["name"],state["phone"],state["address"])
    cur.execute("""INSERT INTO orders(user_id,name,phone,address,items,total,status,created_at,payment_method) VALUES(?,?,?,?,?,?,?,?,?)""",
        (uid,state["name"],state["phone"],state["address"],state["items"],state["total"],"Yangi",created,state["payment_method"]))
    oid=cur.lastrowid; cur.execute("DELETE FROM cart WHERE user_id=?",(uid,)); db.commit(); db.close(); order_states.pop(uid,None)
    await callback.message.answer(f"✅ BUYURTMANGIZ QABUL QILINDI!\n\n📦 Buyurtma №{oid}\n💰 Jami: {state['total']:,} so‘m\n💳 To‘lov: {state['payment_method']}\n\nTez orada siz bilan bog‘lanamiz.",reply_markup=main_menu())
    if ADMIN_ID:
        try:
            await bot.send_message(int(ADMIN_ID),f"🔔 YANGI BUYURTMA!\n\n📦 №{oid}\n👤 {state['name']}\n📞 {state['phone']}\n📍 {state['address']}\n💳 {state['payment_method']}\n\n🛍 Mahsulotlar:\n{state['items']}💰 Jami: {state['total']:,} so‘m\n🕐 {created}")
        except Exception as e: print("Admin xabari xatosi:",e)
    await callback.answer()


@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback: CallbackQuery):
    order_states.pop(callback.from_user.id,None); await callback.message.answer("❌ Buyurtma bekor qilindi.",reply_markup=main_menu()); await callback.answer()


@dp.callback_query(F.data == "orders")
async def orders_callback(callback: CallbackQuery):
    uid=callback.from_user.id; db=get_db(); cur=db.cursor(); cur.execute("SELECT id,total,status,created_at,payment_method FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",(uid,)); rows=cur.fetchall(); db.close()
    if not rows: await callback.message.edit_text("📦 Sizda hozircha buyurtmalar yo‘q.",reply_markup=back_home()); await callback.answer(); return
    text="📦 BUYURTMALARIM\n\n"+"".join(f"№{oid}\n💰 {total:,} so'm\n📌 Holat: {status}\n💳 {pay}\n🕐 {created}\n\n" for oid,total,status,created,pay in rows)
    await callback.message.edit_text(text,reply_markup=back_home()); await callback.answer()


@dp.callback_query(F.data == "payment_info")
async def payment_info(callback: CallbackQuery):
    text=("💳 TO‘LOV USULLARI\n\n"
          "💳 Karta orqali — karta/online to‘lov\n"
          "💵 Naqd pul — yetkazib berilganda\n"
          "🏪 Joyida to‘lov — do‘konda/kelishilgan joyda\n\n"
          "Eslatma: karta orqali avtomatik onlayn to‘lov ishlashi uchun Click/Payme yoki Telegram Payments kabi provayder ma’lumotlari kerak bo‘ladi.")
    await callback.message.edit_text(text,reply_markup=back_home()); await callback.answer()


@dp.callback_query(F.data == "contact")
async def contact_callback(callback: CallbackQuery):
    await callback.message.edit_text(f"📞 Aloqa\n\nTelefon: {CONTACT_PHONE}\n📍 Manzil: Mirzo Ulug‘bek tumani",reply_markup=back_home()); await callback.answer()


@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    uid=callback.from_user.id; name,phone,address=profile_get(uid)
    text=f"👤 PROFILIM\n\n👤 Ism: {name or 'Kiritilmagan'}\n📞 Telefon: {phone or 'Kiritilmagan'}\n📍 Manzil: {address or 'Kiritilmagan'}"
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o‘zgartirish",callback_data="profile_edit:name")],
        [InlineKeyboardButton(text="📞 Telefonni o‘zgartirish",callback_data="profile_edit:phone")],
        [InlineKeyboardButton(text="📍 Manzilni o‘zgartirish",callback_data="profile_edit:address")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",callback_data="home")],
    ])
    await callback.message.edit_text(text,reply_markup=kb); await callback.answer()


@dp.callback_query(F.data.startswith("profile_edit:"))
async def profile_edit(callback: CallbackQuery):
    field=callback.data.split(":")[1]; uid=callback.from_user.id
    profile_states[uid]=field
    prompts={"name":"👤 Yangi ismingizni yozing:","phone":"📞 Telefon raqamingizni yuboring:","address":"📍 Yangi manzilingizni yozing:"}
    if field=="phone": await callback.message.answer(prompts[field],reply_markup=phone_keyboard())
    else: await callback.message.answer(prompts[field])
    await callback.answer()


@dp.message(F.contact)
async def contact_received(message: Message):
    uid=message.from_user.id
    if uid in profile_states and profile_states[uid]=="phone":
        profile_save(uid,phone=message.contact.phone_number); profile_states.pop(uid,None)
        await message.answer("✅ Telefon saqlandi.",reply_markup=main_menu()); return
    if uid in order_states and order_states[uid].get("step")=="phone":
        order_states[uid]["phone"]=message.contact.phone_number; order_states[uid]["step"]="address"
        await message.answer("📍 Endi yetkazib berish manzilingizni yozing:",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],resize_keyboard=True)); return


@dp.callback_query(F.data == "search")
async def search_callback(callback: CallbackQuery):
    search_states.add(callback.from_user.id); await callback.message.answer("🔎 Mahsulot nomini yozing. Masalan: Coca-Cola"); await callback.answer()


async def perform_search(message, query):
    db=get_db(); cur=db.cursor(); like=f"%{query}%"; cur.execute("SELECT id,name,price,old_price,is_discount,is_new FROM products WHERE name LIKE ? ORDER BY id DESC LIMIT 30",(like,)); rows=cur.fetchall(); db.close()
    if not rows: await message.answer(f"🔎 '{query}' bo‘yicha mahsulot topilmadi.",reply_markup=main_menu()); return
    await message.answer(f"🔎 Natijalar: {query}",reply_markup=products_keyboard_for_rows(rows,"home"))


@dp.message(F.text)
async def text_messages(message: Message):
    uid=message.from_user.id; text=message.text or ""
    if uid in search_states:
        search_states.discard(uid); await perform_search(message,text.strip()); return

    if uid in profile_states:
        field=profile_states.pop(uid)
        if text=="❌ Bekor qilish": await message.answer("❌ Bekor qilindi.",reply_markup=main_menu()); return
        if field=="name": profile_save(uid,name=text.strip())
        elif field=="address": profile_save(uid,address=text.strip())
        await message.answer("✅ Profil ma’lumoti saqlandi.",reply_markup=main_menu()); return

    if is_admin(uid) and uid in admin_states:
        state=admin_states[uid]
        if text=="❌ Bekor qilish": admin_states.pop(uid,None); await message.answer("❌ Amal bekor qilindi.",reply_markup=admin_keyboard()); return
        if state["step"]=="name":
            if len(text.strip())<2: await message.answer("Mahsulot nomini to‘liqroq yozing:"); return
            state["name"]=text.strip(); state["step"]="price"; await message.answer("2️⃣ Mahsulot narxini faqat raqam bilan yozing. Masalan: 15000"); return
        if state["step"] in ("price","old_price"):
            n=text.replace(" ","").replace(",","")
            if not n.isdigit() or int(n)<=0: await message.answer("❗ Narx noto‘g‘ri. Masalan: 15000"); return
            if state["step"]=="price": state["price"]=int(n); state["step"]="category"; await message.answer("3️⃣ Kategoriyani tanlang:",reply_markup=admin_category_keyboard()); return
            state["old_price"]=int(n); state["step"]="photo"; await message.answer("📷 Endi mahsulot rasmini yuboring:"); return

    if uid not in order_states: return
    state=order_states[uid]
    if text=="❌ Bekor qilish": order_states.pop(uid,None); await message.answer("❌ Buyurtma bekor qilindi.",reply_markup=main_menu()); return
    if state["step"]=="name":
        if len(text.strip())<2: await message.answer("Ismingizni to‘liqroq yozing:"); return
        state["name"]=text.strip(); profile_save(uid,name=state["name"]); state["step"]="phone"
        await message.answer("📞 Telefon raqamingizni yuboring:",reply_markup=phone_keyboard()); return
    if state["step"]=="phone":
        if len(text.strip())<7: await message.answer("📞 Telefon raqamni to‘g‘ri kiriting:"); return
        state["phone"]=text.strip(); profile_save(uid,phone=state["phone"]); state["step"]="address"; await message.answer("📍 Yetkazib berish manzilingizni yozing:"); return
    if state["step"]=="address":
        if len(text.strip())<5: await message.answer("📍 Manzilni to‘liqroq yozing:"); return
        state["address"]=text.strip(); profile_save(uid,address=state["address"]); state["step"]="payment"; await message.answer("💳 To‘lov usulini tanlang:",reply_markup=payment_methods_keyboard()); return


@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery):
    await callback.message.edit_text("🏠 Bosh menyu\n\nKerakli bo‘limni tanlang:",reply_markup=main_menu()); await callback.answer()


async def webhook(request: web.Request):
    try:
        data=await request.json(); update=Update.model_validate(data,context={"bot":bot}); await dp.feed_update(bot,update); return web.Response(text="OK")
    except Exception as e:
        print("Webhook error:",e); return web.Response(text="ERROR",status=500)


async def health(request: web.Request): return web.Response(text="777MAZ bot is running")


async def on_startup(app):
    init_db(); seed_products()
    base_url=os.environ.get("RENDER_EXTERNAL_URL")
    if not base_url: raise RuntimeError("RENDER_EXTERNAL_URL topilmadi")
    secret=os.environ.get("WEBHOOK_SECRET","777maz-secret")
    webhook_url=f"{base_url}/webhook/{secret}"; await bot.set_webhook(webhook_url); print(f"Webhook set: {webhook_url}")


async def on_cleanup(app):
    try: await bot.delete_webhook()
    except Exception as e: print("Webhook delete error:",e)
    await bot.session.close()


def create_app():
    app=web.Application(); secret=os.environ.get("WEBHOOK_SECRET","777maz-secret")
    app.router.add_get("/",health); app.router.add_post(f"/webhook/{secret}",webhook)
    app.on_startup.append(on_startup); app.on_cleanup.append(on_cleanup); return app


if __name__=="__main__":
    web.run_app(create_app(),host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
