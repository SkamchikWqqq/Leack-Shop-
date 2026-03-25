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
    kb.add(InlineKeyboardButton(text=f"💳 Оплатить {amount}$", url=invoice_url))
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
            add_balance(referred_by, REFERRAL_BALANCE_BONUS)  # +2 рубля на баланс
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
    await callback.message.edit_caption(
        caption="🗂 <b>Каталог</b>\n\nВыбери раздел:",
        reply_markup=catalog_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="cat_osint")
async def cat_osint(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="🔍 <b>Os1nt</b>\n\nВыбери тариф:",
        reply_markup=osint_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="cat_sniper")
async def cat_sniper(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="🎯 <b>SN##ER</b>\n\nВыбери тариф:",
        reply_markup=sniper_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="cat_edu")
async def cat_edu(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="📚 <b>0БУЧЕНИЕ</b>\n\nВыбери тариф:",
        reply_markup=edu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# --------- ОПЛАТА ---------
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("pay_"))
async def handle_payment(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    amount = float(parts[-1])
    section = parts[1].upper()
    tier = parts[2].upper()

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
            await callback.message.edit_caption(
                caption=(
                    f"💳 <b>Оплата</b>\n\n"
                    f"Раздел: <b>{section}</b>\n"
                    f"Тариф: <b>{label}</b>\n"
                    f"Сумма: <b>{amount}$</b>\n\n"
                    f"Нажми кнопку ниже после оплаты."
                ),
                reply_markup=payment_confirmation_kb(invoice_url, amount, label),
                parse_mode="HTML"
            )
        else:
            raise Exception("CryptoBot error")
    except Exception:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog"))
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


# --------- ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ---------
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery):
    amount = callback.data.split("_")[-1]
    with open(IMAGE_PATH, "rb") as photo:
        await callback.message.answer_photo(
            photo=photo,
            caption=(
                f"✅ <b>Спасибо за оплату!</b>\n\n"
                f"Сумма: <b>{amount}$</b>\n\n"
                f"Свяжись с @cunpar для получения доступа к услуге."
            ),
            reply_markup=main_menu_kb(callback.from_user.id),
            parse_mode="HTML"
        )
    await callback.answer()


# --------- ПРОФИЛЬ ---------
@dp.callback_query_handler(text="profile")
async def profile(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    user_id, username, balance, ref_balance, referred_by, reg_date, adm = user
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Юзернейм: @{username or '—'}\n"
        f"📅 Дата регистрации: {reg_date}\n"
        f"💰 Баланс: <b>{balance:.2f}₽</b>\n"
        f"🔗 Реферальный баланс: <b>{ref_balance:.2f}₽</b>\n"
    )
    await callback.message.edit_caption(
        caption=text,
        reply_markup=profile_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="pay_history")
async def pay_history(callback: types.CallbackQuery):
    history = get_payment_history(callback.from_user.id)
    if not history:
        text = "📋 <b>История пополнений</b>\n\nПополнений пока нет."
    else:
        lines = ["📋 <b>История пополнений</b>\n"]
        for amount, currency, status, created_at in history:
            lines.append(f"• {created_at} — {amount} {currency} [{status}]")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="profile"))
    await callback.message.edit_caption(
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="withdraw")
async def withdraw(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    
    balance = user[2]
    if balance < 500:
        await callback.answer(
            f"❌ Минимальная сумма вывода: 500₽\n\nТвой баланс: {balance:.2f}₽",
            show_alert=True
        )
        return
    
    text = (
        f"💸 <b>Вывод денег</b>\n\n"
        f"Твой баланс: <b>{balance:.2f}₽</b>\n\n"
        f"Минимум для вывода: <b>500₽</b>\n\n"
        f"Для вывода свяжись с @cunpar"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="profile"))
    await callback.message.edit_caption(
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="topup")
async def topup_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Отмена", callback_data="profile"))
    await callback.message.edit_caption(
        caption="💰 <b>Пополнение баланса</b>\n\nВведи сумму в USDT (например: 5):",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await UserStates.waiting_topup_amount.set()
    await callback.answer()

@dp.message_handler(state=UserStates.waiting_topup_amount)
async def topup_amount(message: types.Message, state: FSMContext):
    await state.finish()
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи корректную сумму.")
        return

    try:
        result = await create_invoice(amount=amount, description="Пополнение баланса")
        if result.get("ok"):
            invoice_url = result["result"]["pay_url"]
            invoice_id = result["result"]["invoice_id"]
            save_payment(message.from_user.id, amount, "USDT", str(invoice_id))
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton(text=f"💳 Оплатить {amount} USDT", url=invoice_url))
            kb.add(InlineKeyboardButton(text="✅ Я ОПЛАТИЛ", callback_data=f"confirm_topup_{amount}"))
            with open(IMAGE_PATH, "rb") as photo:
                await message.answer_photo(
                    photo=photo,
                    caption=f"💳 Инвойс на <b>{amount} USDT</b> создан.\n\nНажми кнопку после оплаты.",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
        else:
            raise Exception()
    except Exception:
        await message.answer("⚠️ CryptoBot API не настроен. Вставь токен в конфиг.")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("confirm_topup_"))
async def confirm_topup(callback: types.CallbackQuery):
    amount = callback.data.split("_")[-1]
    with open(IMAGE_PATH, "rb") as photo:
        await callback.message.answer_photo(
            photo=photo,
            caption=(
                f"✅ <b>Спасибо за пополнение!</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n\n"
                f"Свяжись с @cunpar для подтверждения пополнения."
            ),
            reply_markup=main_menu_kb(callback.from_user.id),
            parse_mode="HTML"
        )
    await callback.answer()

@dp.callback_query_handler(text="activate_promo")
async def activate_promo_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Отмена", callback_data="profile"))
    await callback.message.edit_caption(
        caption="🎟 <b>Активация промокода</b>\n\nВведи промокод:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await UserStates.waiting_promo_input.set()
    await callback.answer()

@dp.message_handler(state=UserStates.waiting_promo_input)
async def activate_promo_input(message: types.Message, state: FSMContext):
    await state.finish()
    code = message.text.strip().upper()
    amount, err = use_promo(code, message.from_user.id)
    if err:
        with open(IMAGE_PATH, "rb") as photo:
            await message.answer_photo(
                photo=photo,
                caption=err,
                reply_markup=main_menu_kb(message.from_user.id)
            )
    else:
        with open(IMAGE_PATH, "rb") as photo:
            await message.answer_photo(
                photo=photo,
                caption=f"✅ Промокод активирован! +{amount:.0f}₽ на баланс.",
                reply_markup=main_menu_kb(message.from_user.id)
            )


# --------- РЕФЕРАЛЫ ---------
@dp.callback_query_handler(text="referrals")
async def referrals(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={user_id}"
    user = get_user(user_id)
    ref_balance = user[3] if user else 0
    text = (
        f"🔗 <b>Рефералы</b>\n\n"
        f"Твоя реферальная ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"💸 За каждого приглашённого — <b>{REFERRAL_BONUS}₽</b> на реферальный баланс\n"
        f"💰 Бонус на основной баланс: <b>+{REFERRAL_BALANCE_BONUS}₽</b>\n"
        f"🎁 Твой реферальный баланс: <b>{ref_balance:.2f}₽</b>"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    await callback.message.edit_caption(
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


# --------- РАССЫЛКА (АДМИН) ---------
@dp.callback_query_handler(text="broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_menu"))
    await callback.message.edit_caption(
        caption="📣 <b>Рассылка</b>\n\nНапиши сообщение для рассылки:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await AdminStates.waiting_broadcast.set()
    await callback.answer()

@dp.message_handler(state=AdminStates.waiting_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    await state.finish()
    if not is_admin(message.from_user.id):
        return
    users = get_all_users()
    sent = 0
    for uid in users:
        try:
            with open(IMAGE_PATH, "rb") as photo:
                await bot.send_photo(
                    chat_id=uid,
                    photo=photo,
                    caption=message.text,
                    parse_mode="HTML"
                )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    with open(IMAGE_PATH, "rb") as photo:
        await message.answer_photo(
            photo=photo,
            caption=f"✅ Рассылка завершена. Отправлено: {sent}/{len(users)}",
            reply_markup=main_menu_kb(message.from_user.id)
        )


# --------- ГЕНЕРАЦИЯ ПРОМО (АДМИН) ---------
@dp.callback_query_handler(text="gen_promo")
async def gen_promo_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_caption(
        caption="🎟 <b>Генерация промокода</b>\n\nКак создать код?",
        reply_markup=promo_type_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query_handler(text="promo_manual")
async def promo_manual(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(promo_type="manual")
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_menu"))
    await callback.message.edit_caption(
        caption="✍️ Введи текст промокода:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await AdminStates.waiting_promo_code.set()
    await callback.answer()

@dp.callback_query_handler(text="promo_random")
async def promo_random(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    await state.update_data(promo_type="random", promo_code=code)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_menu"))
    await callback.message.edit_caption(
        caption=f"🎲 Рандомный код: <code>{code}</code>\n\nНа сколько активаций?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await AdminStates.waiting_promo_uses.set()
    await callback.answer()

@dp.message_handler(state=AdminStates.waiting_promo_code)
async def promo_code_input(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.update_data(promo_code=code)
    await message.answer(
        "На сколько активаций (введи число):",
        reply_markup=ReplyKeyboardRemove()
    )
    await AdminStates.waiting_promo_uses.set()

@dp.message_handler(state=AdminStates.waiting_promo_uses)
async def promo_uses_input(message: types.Message, state: FSMContext):
    try:
        uses = int(message.text.strip())
        if uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи корректное число.")
        return
    await state.update_data(promo_uses=uses)
    await message.answer("На сколько рублей будет промокод?")
    await AdminStates.waiting_promo_amount.set()

@dp.message_handler(state=AdminStates.waiting_promo_amount)
async def promo_amount_input(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи корректную сумму.")
        return
    data = await state.get_data()
    code = data.get("promo_code")
    uses = data.get("promo_uses", 1)
    await state.finish()
    create_promo(code, amount, uses, message.from_user.id)
    with open(IMAGE_PATH, "rb") as photo:
        await message.answer_photo(
            photo=photo,
            caption=(
                f"✅ <b>Промокод создан!</b>\n\n"
                f"🔑 Код: <code>{code}</code>\n"
                f"🔄 Активаций: {uses}\n"
                f"💰 Сумма: {amount:.0f}₽"
            ),
            reply_markup=main_menu_kb(message.from_user.id),
            parse_mode="HTML"
        )


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    init_db()
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)