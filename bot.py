import asyncio
import logging
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

# ── Конфиг ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = "8941601081:AAFfcQnlqxAcg6hz7KsB-ig-zfB6-Imn7-8"        # от @BotFather
OWNER_ID    = 8984419390           # твой Telegram ID — сюда летят логи
# ──────────────────────────────────────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()

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

    # Форматируем время
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
    return web.Response(status=200, text="ok")

async def main():
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.router.add_post("/collect", handle_collect)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("Бот запущен. Слушаю /collect на порту 8080.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
