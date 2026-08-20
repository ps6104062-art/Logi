import asyncio
import logging
import os
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, MenuButtonWebApp, WebAppInfo
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN  = os.environ["BOT_TOKEN"]
OWNER_ID   = int(os.environ["OWNER_ID"])
WEBAPP_URL = "https://ps6104062-art.github.io/Logi/"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=WEBAPP_URL))
    )
    await message.answer("Нажми кнопку ниже 👇")

async def handle_options(request: web.Request) -> web.Response:
    return web.Response(
        status=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )

async def handle_collect(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    name     = data.get("name", "—")
    username = data.get("username", "")
    user_id  = data.get("user_id", "—")
    language = data.get("language", "—")
    city     = data.get("city", "—")
    time_raw = data.get("time", datetime.utcnow().isoformat())

    try:
        dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        time_str = dt.strftime("%d.%m.%Y %H:%M:%S UTC")
    except Exception:
        time_str = time_raw

    username_str = f"@{username}" if username else "нет"

    text = (
        f"🔔 <b>Новое нажатие</b>\n\n"
        f"👤 <b>Имя:</b> {name}\n"
        f"🔗 <b>Username:</b> {username_str}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🌍 <b>Город:</b> {city}\n"
        f"🗣 <b>Язык:</b> {language}\n"
        f"🕐 <b>Время:</b> {time_str}"
    )

    await bot.send_message(OWNER_ID, text)

    return web.Response(
        status=200,
        text="ok",
        headers={"Access-Control-Allow-Origin": "*"}
    )

async def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_route("OPTIONS", "/collect", handle_options)
    app.router.add_post("/collect", handle_collect)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    asyncio.create_task(dp.start_polling(bot))
    print("Бот запущен. Слушаю /collect на порту 8080.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
