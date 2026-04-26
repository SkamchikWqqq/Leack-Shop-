import logging
import os
import asyncio
import sqlite3
import aiohttp
from datetime import datetime
from flask import Flask
from threading import Thread

from aiogram.fsm.state import State, StatesGroup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, FSInputFile, InlineKeyboardMarkup

# 1. НАСТРОЙКА ЛОГИРОВАНИЯ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 2. ВЕБ-СЕРВЕР ДЛЯ RENDER (ЧТОБЫ БОТ НЕ ВЫЛЕТАЛ)
app = Flask(__name__)

@app.route('/')
def index():
    return "Leack Shop Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 3. ТВОИ НАСТРОЙКИ (КОНСТАНТЫ)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8798655968:AAFS1WJYtTzWwg8cDB1kwdTOLTsneZVNmM0")
CRYPTOBOT_API_TOKEN = os.getenv("CRYPTOBOT_API_TOKEN", "553441:AAd905Dra8Qp1GdSHuBbnWJNj8DfZYIXljf")

ADMIN_IDS = []
ADMIN_USERNAMES = ["cunpar"]
CHANNEL_ID = -1002415070098
CHANNEL_INVITE = "https://t.me/+yO5vZ2dUyRE3MzM0"
REFERRAL_BONUS = 2
REFERRAL_BALANCE_BONUS = 2
IMAGE_PATH = "paranoia_attack.png"

# 4. ИНИЦИАЛИЗАЦИЯ ОБЪЕКТОВ (ИСПРАВЛЕНО ДЛЯ AIOGRAM 3.x)
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ============================================================
# НАСТРОЙКА БОТА
# ============================================================
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
# Создаем хранилище в памяти
storage = MemoryStorage()

# Правильная инициализация диспетчера для aiogram 3.x
dp = Dispatcher(storage=storage)


# ============================================================
# БД
# ============================================================
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        ref_balance REAL DEFAULT 0,
        referred_by INTEGER,
        reg_date TEXT,
        is_admin INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promos (
        code TEXT PRIMARY KEY,
        amount REAL,
        max_uses INTEGER,
        used INTEGER DEFAULT 0,
        created_by INTEGER,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_uses (
        code TEXT,
        user_id INTEGER,
        PRIMARY KEY (code, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        currency TEXT,
        invoice_id TEXT,
        status TEXT,
        created_at TEXT
    )""")

    # --- ДОБАВЬ ЭТУ СТРОКУ ПРЯМО ЗДЕСЬ ---
    c.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, url TEXT)")
    # ------------------------------------

    conn.commit()
    conn.close()

def add_channel_db(channel_id, url):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO channels (channel_id, url) VALUES (?, ?)", (str(channel_id), url))
    conn.commit()
    conn.close()

def get_channels_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT channel_id, url FROM channels")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_channel_db(channel_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE channel_id = ?", (str(channel_id),))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def register_user(user_id, username, referred_by=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, reg_date, referred_by) VALUES (?,?,?,?)",
              (user_id, username, datetime.now().strftime("%d.%m.%Y %H:%M"), referred_by))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0] == 1:
        return True
    return False

def set_admin(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_ref_balance(user_id, amount):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET ref_balance = ref_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def add_balance(user_id, amount):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def create_promo(code, amount, max_uses, created_by):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO promos VALUES (?,?,?,0,?,?)",
              (code, amount, max_uses, created_by, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()

def use_promo(code, user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM promos WHERE code=?", (code,))
    promo = c.fetchone()
    if not promo:
        conn.close()
        return None, "❌ Промокод не найден."
    if promo[3] >= promo[2]:
        conn.close()
        return None, "❌ Промокод уже исчерпан."
    c.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, user_id))
    if c.fetchone():
        conn.close()
        return None, "❌ Ты уже использовал этот промокод."
    c.execute("UPDATE promos SET used=used+1 WHERE code=?", (code,))
    c.execute("INSERT INTO promo_uses VALUES (?,?)", (code, user_id))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (promo[1], user_id))
    conn.commit()
    conn.close()
    return promo[1], None

def get_payment_history(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT amount, currency, status, created_at FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_payment(user_id, amount, currency, invoice_id, status="pending"):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, amount, currency, invoice_id, status, created_at) VALUES (?,?,?,?,?,?)",
              (user_id, amount, currency, invoice_id, status, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()
    # ============================================================
# FSM STATES
# ============================================================
class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_promo_code = State()
    waiting_promo_uses = State()
    waiting_promo_amount = State()
    promo_type = State()
    waiting_channel_data = State()

class UserStates(StatesGroup):
    waiting_promo_input = State()
    waiting_topup_amount = State()
    waiting_payment_confirmation = State()

# ============================================================
# ЗВЁЗДЫ — цены по тарифам
# ============================================================
STARS_PRICES = {
    "osint": {"basic": 50, "mid": 100, "vip": 250},
    "sniper": {"basic": 75, "mid": 200, "strong": 500},
    "edu": {"basic": 50, "mid": 150, "vip": 250},
}

# ============================================================
# КЛАВИАТУРЫ (aiogram 3.x)
# ============================================================

def main_menu_kb(user_id=None):
    admin = is_admin(user_id) if user_id else False
    builder = InlineKeyboardBuilder()
    
    builder.row(InlineKeyboardButton(text="🗂 Каталог", callback_data="catalog"))
    builder.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    builder.row(InlineKeyboardButton(text="🔗 Рефералы", callback_data="referrals"))
    
    if admin:
        builder.row(InlineKeyboardButton(text="📣 Рассылка", callback_data="broadcast"))
        builder.row(InlineKeyboardButton(text="🎟 Генерация промо", callback_data="gen_promo"))
    
builder.row(InlineKeyboardButton(text="➕ Добавить ОП", callback_data="admin_add_channel"))
        builder.row(InlineKeyboardButton(text="❌ Удалить ОП", callback_data="admin_list_channels"))

    return builder.as_markup()

def catalog_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Os1nt", callback_data="cat_osint"))
    builder.row(InlineKeyboardButton(text="SN##ER", callback_data="cat_sniper"))
    builder.row(InlineKeyboardButton(text="0БУЧЕНИЕ", callback_data="cat_edu"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return builder.as_markup()

def osint_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Базовый — 2$", callback_data="pay_osint_basic_2"))
    builder.row(InlineKeyboardButton(text="Средний — 3$", callback_data="pay_osint_mid_3"))
    builder.row(InlineKeyboardButton(text="VIP — 5$", callback_data="pay_osint_vip_5"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return builder.as_markup()

def sniper_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Базовый — 3$", callback_data="pay_sniper_basic_3"))
    builder.row(InlineKeyboardButton(text="Средний — 7$", callback_data="pay_sniper_mid_7"))
    builder.row(InlineKeyboardButton(text="Сильный — 10$", callback_data="pay_sniper_strong_10"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return builder.as_markup()

def edu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Базовое — 2$", callback_data="pay_edu_basic_2"))
    builder.row(InlineKeyboardButton(text="Среднее — 5$", callback_data="pay_edu_mid_5"))
    builder.row(InlineKeyboardButton(text="VIP — 8$", callback_data="pay_edu_vip_8"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return builder.as_markup()

def payment_confirmation_kb(invoice_url, amount, label):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 CryptoBot", url=invoice_url))
    builder.row(InlineKeyboardButton(text=f"⭐ Звёзды ({int(amount)}$)", callback_data=f"pay_stars_{int(amount)}"))
    builder.row(InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"confirm_payment_{amount}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return builder.as_markup()

def profile_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup"))
    builder.row(InlineKeyboardButton(text="💸 Вывести деньги", callback_data="withdraw"))
    builder.row(InlineKeyboardButton(text="📋 История пополнений", callback_data="pay_history"))
    builder.row(InlineKeyboardButton(text="🎟 Активировать промокод", callback_data="activate_promo"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return builder.as_markup()

def promo_type_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✍️ Вручную", callback_data="promo_manual"))
    builder.row(InlineKeyboardButton(text="🎲 Рандомно", callback_data="promo_random"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return builder.as_markup()

# ============================================================
# ОБНОВЛЕННАЯ ПРОВЕРКА ПОДПИСКИ (ДЛЯ ВСЕХ КАНАЛОВ ИЗ БАЗЫ)
# ============================================================
async def check_subscription(bot: Bot, user_id: int) -> bool:
    channels = get_channels_db()
    if not channels:
        return True # Если в базе нет каналов, доступ разрешен
    
    for cid, url in channels:
        try:
            member = await bot.get_chat_member(chat_id=cid, user_id=user_id)
            if member.status in ("left", "kicked"):
                return False # Нашел канал, на который юзер не подписан
        except Exception:
            continue # Если ошибка (например, бота выгнали из канала), идем дальше
    return True

def sub_check_kb():
    # Теперь эта функция будет вызываться динамически в CommandStart
    # Мы создадим кнопки прямо там, так как ссылки теперь в базе
    pass 

# ============================================================
# CRYPTOBOT
# ============================================================
async def create_invoice(amount: float, currency: str = "USDT", description: str = "Оплата") -> dict:
    import aiohttp
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN}
    data = {
        "asset": currency,
        "amount": str(amount),
        "description": description,
        "expires_in": 3600
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()
            return result

 #============================================================
# ИСПРАВЛЕННЫЕ ХЭНДЛЕРЫ ============================================================

async def send_main_menu(user_id: int, chat_id: int):
    """Отправка главного меню с проверкой наличия фото"""
    try:
        photo = FSInputFile(IMAGE_PATH)
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption="🏠 <b>Главное меню</b>\n\nВыбери раздел:",
            reply_markup=main_menu_kb(user_id)
        )
    except Exception as e:
        # Если фото не найдено или ошибка — отправляем просто текст
        print(f"Ошибка при отправке фото: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="🏠 <b>Главное меню</b>\n\nВыбери раздел:",
            reply_markup=main_menu_kb(user_id)
        )

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    referred_by = None
    
    # Логика рефералов
    if len(args) > 1:
        try:
            referred_by = int(args[1])
            if referred_by == user.id:
                referred_by = None
        except ValueError:
            referred_by = None

    existing = get_user(user.id)
    if not existing:
        register_user(user.id, user.username, referred_by)
        if referred_by and get_user(referred_by):
            add_ref_balance(referred_by, REFERRAL_BONUS)
            add_balance(referred_by, REFERRAL_BALANCE_BONUS)
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 По твоей реф-ссылке зарегистрировался новый пользователь!\n"
                    f"💸 +{REFERRAL_BONUS}₽ на реферальный баланс.\n"
                    f"💰 +{REFERRAL_BALANCE_BONUS}₽ на основной баланс."
                )
            except Exception:
                pass

    if user.username and user.username.lower() in ADMIN_USERNAMES:
        set_admin(user.id)

    # ПРОВЕРКА ПОДПИСКИ (Обязательно передаем bot)
    subscribed = await check_subscription(bot, user.id) 
    if not subscribed:
        try:
            photo = FSInputFile(IMAGE_PATH)
            await message.answer_photo(
                photo=photo,
                caption=(
                    "👋 Добро пожаловать!\n\n"
                    "❗️ Для доступа к боту необходимо подписаться на наш канал."
                ),
                reply_markup=sub_check_kb()
            )
        except Exception:
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "❗️ Для доступа к боту необходимо подписаться на наш канал.",
                reply_markup=sub_check_kb()
            )
        return

    await send_main_menu(message.from_user.id, message.chat.id)

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    # ИСПРАВЛЕНО: Добавлен аргумент callback.bot
    subscribed = await check_subscription(callback.bot, callback.from_user.id)
    
    if not subscribed:
        await callback.answer("❌ Ты ещё не подписался на канал!", show_alert=True)
        return
    
    # Если подписался — удаляем старое и шлем меню
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    await send_main_menu(callback.from_user.id, callback.message.chat.id)
    await callback.answer()

# --------- КАТАЛОГ ---------
@dp.callback_query(F.data == "catalog")
async def catalog(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🗂 <b>Каталог</b>\n\nВыбери раздел:",
            reply_markup=catalog_kb()
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "cat_osint")
async def cat_osint(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🔍 <b>Os1nt</b>\n\nВыбери тариф:",
            reply_markup=osint_kb()
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "cat_sniper")
async def cat_sniper(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🎯 <b>SN##ER</b>\n\nВыбери тариф:",
            reply_markup=sniper_kb()
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "cat_edu")
async def cat_edu(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="📚 <b>0БУЧЕНИЕ</b>\n\nВыбери тариф:",
            reply_markup=edu_kb()
        )
    except Exception:
        pass
    await callback.answer()

# ============================================================
# ВСЕ ХЕНДЛЕРЫ КНОПОК (ИСПРАВЛЕНО)
# ============================================================

# --- ГЛАВНОЕ МЕНЮ ---

@dp.callback_query(F.data == "catalog")
async def process_catalog(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="🗂 <b>Каталог товаров</b>\n\nВыбери нужную категорию:",
        reply_markup=catalog_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def process_profile(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    balance = user[2] if user else 0
    await callback.message.edit_caption(
        caption=f"👤 <b>Ваш профиль</b>\n\n🆔 ID: <code>{callback.from_user.id}</code>\n💰 Баланс: <b>{balance}$</b>",
        reply_markup=profile_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "referrals")
async def process_referrals(callback: types.CallbackQuery):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={callback.from_user.id}"
    await callback.message.edit_caption(
        caption=f"🔗 <b>Реферальная система</b>\n\nВаша ссылка для приглашения:\n<code>{ref_link}</code>",
        reply_markup=back_to_menu_kb() # Убедись, что эта функция создана или замени на main_menu_kb()
    )
    await callback.answer()

# --- КАТЕГОРИИ КАТАЛОГА ---

@dp.callback_query(F.data == "cat_osint")
async def process_osint(callback: types.CallbackQuery):
    await callback.message.edit_caption(caption="🔍 <b>Os1nt</b>\n\nВыберите тариф:", reply_markup=osint_kb())
    await callback.answer()

@dp.callback_query(F.data == "cat_sniper")
async def process_sniper(callback: types.CallbackQuery):
    await callback.message.edit_caption(caption="🎯 <b>SN##ER</b>\n\nВыберите тариф:", reply_markup=sniper_kb())
    await callback.answer()

@dp.callback_query(F.data == "cat_edu")
async def process_edu(callback: types.CallbackQuery):
    await callback.message.edit_caption(caption="📚 <b>0БУЧЕНИЕ</b>\n\nВыберите тариф:", reply_markup=edu_kb())
    await callback.answer()

# --- КНОПКИ ПРОФИЛЯ ---

@dp.callback_query(F.data == "topup")
async def process_topup(callback: types.CallbackQuery):
    await callback.message.edit_caption(caption="💰 Введите сумму для пополнения баланса:", reply_markup=back_to_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "withdraw")
async def process_withdraw(callback: types.CallbackQuery):
    await callback.answer("❌ Вывод средств временно недоступен", show_alert=True)

@dp.callback_query(F.data == "pay_history")
async def process_pay_history(callback: types.CallbackQuery):
    history = get_payment_history(callback.from_user.id)
    if not history:
        text = "📋 У вас пока нет истории платежей."
    else:
        text = "📋 <b>История последних платежей:</b>\n\n" + "\n".join([f"🔹 {h[0]}$ ({h[1]}) - {h[2]}" for h in history])
    await callback.message.edit_caption(caption=text, reply_markup=back_to_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "activate_promo")
async def process_activate_promo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(caption="🎟 Введите промокод:")
    await state.set_state(UserStates.waiting_promo_input)
    await callback.answer()

# --- АДМИН КНОПКИ ---

@dp.callback_query(F.data == "broadcast")
async def process_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        await callback.message.answer("📣 Введите текст для рассылки всем пользователям:")
        await state.set_state(AdminStates.waiting_broadcast)
    else:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == "gen_promo")
async def process_gen_promo(callback: types.CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.message.edit_caption(caption="🎟 Выберите тип промокода:", reply_markup=promo_type_kb())
    else:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
    await callback.answer()

# --- СИСТЕМНЫЕ ---

@dp.callback_query(F.data == "back_menu")
async def process_back_menu(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
    await send_main_menu(callback.from_user.id, callback.message.chat.id)
    await callback.answer()


# --------- ПОЛНЫЙ БЛОК ОПЛАТЫ (CryptoBot + Stars) ---------
@dp.callback_query(F.data.startswith("pay_"))
async def handle_all_payments(callback: types.CallbackQuery):
    # 1. Сначала проверяем, не нажали ли уже на конкретную оплату звёздами
    if "pay_stars_" in callback.data:
        parts = callback.data.split("_")
        try:
            stars_amount = int(parts[-1])
        except:
            stars_amount = 50
            
        prices = [types.LabeledPrice(label="Пополнение", amount=stars_amount)]
        
        try:
            # Отправляем счёт ОТДЕЛЬНЫМ сообщением, чтобы ничего не моргало
            await bot.send_invoice(
                chat_id=callback.from_user.id,
                title="Оплата Stars",
                description=f"Зачисление {stars_amount} ⭐",
                payload=f"stars_{stars_amount}",
                provider_token="",
                currency="XTR",
                prices=prices
            )
            await callback.answer()
        except Exception as e:
            await callback.answer(f"❌ Ошибка Stars: {e}")
        return  # ВАЖНО: Останавливаем выполнение здесь, чтобы код ниже не стер кнопки!

    # 2. Если это выбор тарифа (Osint/Sniper)
    parts = callback.data.split("_")
    if len(parts) < 4: 
        return

    category = parts[1].upper()
    tier = parts[2].upper()
    try:
        amount = float(parts[3])
    except: 
        return

    # Показываем уведомление о создании счета
    await callback.answer("⏳ Генерирую способы оплаты...")

    try:
        # Создаем инвойс в CryptoBot
        result = await create_invoice(amount=amount, description=f"{category} {tier}")
        
        if result.get("ok"):
            invoice_url = result["result"]["pay_url"]
            invoice_id = result["result"]["invoice_id"]
            save_payment(callback.from_user.id, amount, "USDT", str(invoice_id))

            # Формируем кнопки
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text=f"💳 Оплатить {amount}$ (Крипта)", url=invoice_url))
            
            # Добавляем кнопку звёзд (1$ = 50 звезд)
            stars_val = int(amount * 50)
            builder.row(InlineKeyboardButton(text=f"⭐ Оплатить {stars_val} Stars", callback_data=f"pay_stars_{stars_val}"))
            
            builder.row(InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"conf_{amount}_{invoice_id}"))
            builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))

            # РЕДАКТИРУЕМ ОДИН РАЗ В САМОМ КОНЦЕ
            await callback.message.edit_caption(
                caption=(
                    f"💳 <b>Оплата тарифа</b>\n\n"
                    f"Раздел: <b>{category}</b>\n"
                    f"Тариф: <b>{tier}</b>\n"
                    f"Сумма: <b>{amount}$</b> / <b>{stars_val} ⭐</b>\n\n"
                    f"Выберите удобный способ оплаты:"
                ),
                reply_markup=builder.as_markup()
            )
        else:
            await callback.answer("❌ Ошибка CryptoBot API", show_alert=True)
            
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

# --- ПОДТВЕРЖДЕНИЕ CRYPTOBOT ---

@dp.callback_query(F.data.startswith("conf_"))
async def confirm_payment(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    amount = float(parts[1])
    invoice_id = parts[2]

    # Имитация проверки (здесь можно добавить запрос к API CryptoBot getInvoices)
    save_payment(callback.from_user.id, amount, "USDT", invoice_id, status="paid")
    add_balance(callback.from_user.id, amount)

    await callback.answer(f"✅ Платеж {amount}$ подтвержден!", show_alert=True)
    await callback.message.edit_caption(
        caption=f"💰 <b>Баланс пополнен!</b>\n\nСумма {amount}$ зачислена на ваш счет.",
        reply_markup=main_menu_kb(callback.from_user.id)
    )

@dp.message(AdminStates.waiting_broadcast)
async def perform_broadcast(message: types.Message, state: FSMContext):
    # Проверка, что ты админ
    if message.from_user.username.lower() not in ADMIN_USERNAMES:
        await state.clear()
        return

    users = get_all_users() # Функция, которая берет всех ID из базы
    count = 0
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    
    for user_id in users:
        try:
            # Если в базе user_id это кортеж (например, (12345,)), берем [0]
            uid = user_id[0] if isinstance(user_id, tuple) else user_id
            await bot.send_message(uid, message.text)
            count += 1
            await asyncio.sleep(0.05) # Чтобы Telegram не забанил за спам
        except Exception:
            continue
            
    await message.answer(f"✅ Рассылка завершена! Сообщение получили {count} человек.")
    await state.clear()

@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.username.lower() not in ADMIN_USERNAMES: return
    await callback.message.answer("Введите ID канала и ссылку через пробел.\nПример:\n-100123456789 https://t.me/channel")
    await state.set_state(AdminStates.waiting_channel_data)
    await callback.answer()

@dp.message(AdminStates.waiting_channel_data)
async def admin_process_add_channel(message: types.Message, state: FSMContext):
    try:
        cid, url = message.text.split(" ")
        add_channel_db(cid, url)
        await message.answer(f"✅ Канал добавлен!")
        await state.clear()
    except:
        await message.answer("❌ Ошибка! Формат: ID[пробел]ССЫЛКА")

@dp.callback_query(F.data == "admin_list_channels")
async def admin_list_channels(callback: types.CallbackQuery):
    channels = get_channels_db()
    if not channels:
        await callback.answer("Список пуст!", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for cid, url in channels:
        builder.row(InlineKeyboardButton(text=f"Удалить {cid}", callback_data=f"del_ch_{cid}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    await callback.message.edit_caption(caption="Список каналов ОП:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_ch_"))
async def admin_del_channel(callback: types.CallbackQuery):
    cid = callback.data.replace("del_ch_", "")
    delete_channel_db(cid)
    await callback.answer("Удалено!", show_alert=True)
    await admin_list_channels(callback)

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    # 1. Инициализация базы данных
    try:
        init_db()
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

    # 2. Запуск Flask (исправленное название функции)
    Thread(target=run_flask, daemon=True).start() 
    
    logger.info("Удаление вебхука и запуск опроса...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 3. Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
