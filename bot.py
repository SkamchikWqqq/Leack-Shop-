import logging
import asyncio
import random
import string
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)

# Фиксация для Windows
import sys
import platform
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = "8798655968:AAEGVzmu2RPbI2z6UqBeuUjZQWkTuWbzGqM"
CRYPTOBOT_API_TOKEN = "553441:AAd905Dra8Qp1GdSHuBbnWJNj8DfZYIXljf"

ADMIN_IDS = []
ADMIN_USERNAMES = ["cunpar"]

CHANNEL_ID = -1002415070098
CHANNEL_INVITE = "https://t.me/+yO5vZ2dUyRE3MzM0"

REFERRAL_BONUS = 2
REFERRAL_BALANCE_BONUS = 2  # +2 рубля на основной баланс при рефере

IMAGE_PATH = "paranoia_attack.png"

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
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb(user_id=None):
    admin = is_admin(user_id) if user_id else False
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="🗂 Каталог", callback_data="catalog"))
    kb.add(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    kb.add(InlineKeyboardButton(text="🔗 Рефералы", callback_data="referrals"))
    if admin:
        kb.add(InlineKeyboardButton(text="📣 Рассылка", callback_data="broadcast"))
        kb.add(InlineKeyboardButton(text="🎟 Генерация промо", callback_data="gen_promo"))
    return kb

def catalog_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="Os1nt", callback_data="cat_osint"))
    kb.add(InlineKeyboardButton(text="SN##ER", callback_data="cat_sniper"))
    kb.add(InlineKeyboardButton(text="0БУЧЕНИЕ", callback_data="cat_edu"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return kb

def osint_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="Базовый — 2$", callback_data="pay_osint_basic_2"))
    kb.add(InlineKeyboardButton(text="Средний — 3$", callback_data="pay_osint_mid_3"))
    kb.add(InlineKeyboardButton(text="VIP — 5$", callback_data="pay_osint_vip_5"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return kb

def sniper_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="Базовый — 3$", callback_data="pay_sniper_basic_3"))
    kb.add(InlineKeyboardButton(text="Средний — 7$", callback_data="pay_sniper_mid_7"))
    kb.add(InlineKeyboardButton(text="Сильный — 10$", callback_data="pay_sniper_strong_10"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return kb

def edu_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="Базовое — 2$", callback_data="pay_edu_basic_2"))
    kb.add(InlineKeyboardButton(text="Среднее — 5$", callback_data="pay_edu_mid_5"))
    kb.add(InlineKeyboardButton(text="VIP — 8$", callback_data="pay_edu_vip_8"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return kb

def payment_confirmation_kb(invoice_url, amount, label):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text=f"💰 CryptoBot", url=invoice_url))
    kb.add(InlineKeyboardButton(text=f"⭐ Звёзды ({int(amount)}$)", callback_data=f"pay_stars_{int(amount)}"))
    kb.add(InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"confirm_payment_{amount}"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
    return kb

def profile_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup"))
    kb.add(InlineKeyboardButton(text="💸 Вывести деньги", callback_data="withdraw"))
    kb.add(InlineKeyboardButton(text="📋 История пополнений", callback_data="pay_history"))
    kb.add(InlineKeyboardButton(text="🎟 Активировать промокод", callback_data="activate_promo"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return kb

def promo_type_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="✍️ Вручную", callback_data="promo_manual"))
    kb.add(InlineKeyboardButton(text="🎲 Рандомно", callback_data="promo_random"))
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return kb

# ============================================================
# ПРОВЕРКА ПОДПИСКИ
# ============================================================
async def check_subscription(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def sub_check_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_INVITE))
    kb.add(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub"))
    return kb

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

# ============================================================
# БОТ И ДИСПЕТЧЕР
# ============================================================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)

# ============================================================
# ХЭНДЛЕРЫ
# ============================================================
async def send_main_menu(user_id: int, chat_id: int):
    with open(IMAGE_PATH, "rb") as photo:
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption="🏠 <b>Главное меню</b>\n\nВыбери раздел:",
            reply_markup=main_menu_kb(user_id),
            parse_mode="HTML"
        )


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    user = message.from_user
    args = message.text.split()
    referred_by = None
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
                await bot.send_message(referred_by,
                    f"🎉 По твоей реф-ссылке зарегистрировался новый пользователь!\n"
                    f"💸 +{REFERRAL_BONUS}₽ на реферальный баланс.\n"
                    f"💰 +{REFERRAL_BALANCE_BONUS}₽ на основной баланс.")
            except Exception:
                pass

    if user.username and user.username.lower() in ADMIN_USERNAMES:
        set_admin(user.id)

    subscribed = await check_subscription(bot, user.id)
    if not subscribed:
        with open(IMAGE_PATH, "rb") as photo:
            await message.answer_photo(
                photo=photo,
                caption=(
                    "👋 Добро пожаловать!\n\n"
                    "❗️ Для доступа к боту необходимо подписаться на наш канал."
                ),
                reply_markup=sub_check_kb()
            )
        return

    await send_main_menu(message.from_user.id, message.chat.id)


@dp.callback_query_handler(text="check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    subscribed = await check_subscription(bot, callback.from_user.id)
    if not subscribed:
        await callback.answer("❌ Ты ещё не подписался на все каналы!", show_alert=True)
        return
    await callback.message.delete()
    await send_main_menu(callback.from_user.id, callback.message.chat.id)
    await callback.answer()


@dp.callback_query_handler(text="back_menu", state="*")
async def back_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback.message.delete()
    await send_main_menu(callback.from_user.id, callback.message.chat.id)
    await callback.answer()


# --------- КАТАЛОГ ---------
@dp.callback_query_handler(text="catalog")
async def catalog(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🗂 <b>Каталог</b>\n\nВыбери раздел:",
            reply_markup=catalog_kb(),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query_handler(text="cat_osint")
async def cat_osint(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🔍 <b>Os1nt</b>\n\nВыбери тариф:",
            reply_markup=osint_kb(),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query_handler(text="cat_sniper")
async def cat_sniper(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="🎯 <b>SN##ER</b>\n\nВыбери тариф:",
            reply_markup=sniper_kb(),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query_handler(text="cat_edu")
async def cat_edu(callback: types.CallbackQuery):
    try:
        await callback.message.edit_caption(
            caption="📚 <b>0БУЧЕНИЕ</b>\n\nВыбери тариф:",
            reply_markup=edu_kb(),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()


# --------- ОПЛАТА ---------
# ВАЖНО: хендлер pay_stars_ должен быть ВЫШЕ handle_payment,
# иначе handle_payment перехватит колбэк pay_stars_X первым

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("pay_stars_"))
async def pay_stars(callback: types.CallbackQuery):
    # Формат: pay_stars_{section}_{tier}
    parts = callback.data.split("_")
    # Поддержка старого формата (просто число) и нового (section_tier)
    if len(parts) == 4:
        section = parts[2].lower()
        tier = parts[3].lower()
        stars_amount = STARS_PRICES.get(section, {}).get(tier, 50)
    else:
        # fallback: просто число
        stars_amount = int(parts[-1])
    prices = [types.LabeledPrice(label="Услуга", amount=stars_amount)]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Оплата услуги",
        description=f"Оплата {stars_amount}⭐ через Telegram Stars",
        payload=f"stars_{stars_amount}_{callback.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=prices
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("pay_cb_"))
async def pay_cryptobot(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    amount = float(parts[2])
    section = parts[3].upper()
    tier = parts[4].upper()

    label_map = {
        "BASIC": "Базовый", "MID": "Средний", "VIP": "VIP",
        "STRONG": "Сильный"
    }
    label = label_map.get(tier, tier)

    await callback.answer("⏳ Создаю инвойс...", show_alert=False)

    try:
        result = await create_invoice(
            amount=amount,
            currency="USDT",
            description=f"{section} — {label} ({amount}$)"
        )
        if result.get("ok"):
            invoice_url = result["result"]["pay_url"]
            invoice_id = result["result"]["invoice_id"]
            save_payment(callback.from_user.id, amount, "USDT", str(invoice_id))
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton(text=f"💳 Оплатить {amount}$", url=invoice_url))
            kb.add(InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"confirm_payment_{amount}"))
            kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
            try:
                await callback.message.edit_caption(
                    caption=(
                        f"💳 <b>Оплата</b>\n\n"
                        f"Раздел: <b>{section}</b>\n"
                        f"Тариф: <b>{label}</b>\n"
                        f"Сумма: <b>{amount}$</b>\n\n"
                        f"Нажми кнопку ниже после оплаты."
                    ),
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            raise Exception("CryptoBot error")
    except Exception:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
        try:
            await callback.message.edit_caption(
                caption=(
                    f"💳 <b>Оплата</b>\n\n"
                    f"Раздел: <b>{section}</b> | Тариф: <b>{label}</b>\n"
                    f"Сумма: <b>{amount}$</b>\n\n"
                    f"⚠️ CryptoBot API не настроен. Вставь токен в конфиг бота."
                ),
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            pass


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("pay_") and not c.data.startswith("pay_cb_") and not c.data.startswith("pay_stars_"))
async def handle_payment(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    amount = float(parts[-1])
    section = parts[1].lower()
    tier = parts[2].lower()

    label_map = {
        "basic": "Базовый", "mid": "Средний", "vip": "VIP",
        "strong": "Сильный"
    }
    label = label_map.get(ti
import keep_alive

keep_alive.run()  # Запускает Flask сервер
