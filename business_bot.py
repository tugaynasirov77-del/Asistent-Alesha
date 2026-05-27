import asyncio
import logging
import random
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler, ContextTypes, filters,
)

from config import BOT_TOKEN, MY_TELEGRAM_ID
from claude_client import sales_reply
from db import add_message, get_history

log = logging.getLogger(__name__)

READY_MARKER = "[READY_TO_CLOSE]"


async def _handle_dm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return

    # Не отвечаем самому себе
    if user.id == MY_TELEGRAM_ID and not msg.via_bot:
        pass  # хозяин тоже может тестировать — отвечаем

    await ctx.bot.send_chat_action(chat_id=msg.chat_id, action="typing")
    await asyncio.sleep(random.uniform(3, 7))

    history = await get_history(user.id, limit=30)
    try:
        reply = await sales_reply(history, msg.text)
    except Exception as e:
        log.exception("sales_reply failed: %s", e)
        reply = "Секунду, проверю и вернусь 🙏"

    await add_message(user.id, "user", msg.text)
    await add_message(user.id, "assistant", reply)

    clean = reply
    summary = None
    if READY_MARKER in reply:
        idx = reply.index(READY_MARKER)
        clean = reply[:idx].strip()
        summary = reply[idx + len(READY_MARKER):].strip()

    if clean:
        await msg.reply_text(clean)

    if summary is not None:
        uname = f"@{user.username}" if user.username else f"id={user.id}"
        notify = (
            "🔥 Клиент готов закрываться!\n\n"
            f"Кто: {user.full_name} ({uname})\n"
            f"Резюме: {summary or '(пусто)'}\n\n"
            f"Открыть чат: tg://user?id={user.id}"
        )
        try:
            await ctx.bot.send_message(MY_TELEGRAM_ID, notify)
        except Exception as e:
            log.exception("Failed to notify owner: %s", e)


async def _start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я Алёша, ассистент Тугая. Расскажи, что хочешь автоматизировать — разберёмся 🙂"
    )


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, _handle_dm))
    return app


async def run_bot():
    app = build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Business bot started")
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
