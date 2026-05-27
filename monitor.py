import asyncio
import logging
import random
from pyrogram import Client, filters
from pyrogram.types import Message

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_GROUPS,
    SESSION_NAME, MY_TELEGRAM_ID, BOT_TOKEN,
)
from claude_client import detect_lead
from db import save_lead, mark_seen

log = logging.getLogger(__name__)

user_app = Client(
    SESSION_NAME,
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
)

# Отдельный bot-клиент для уведомлений мне (Pyrogram, чтобы делить event loop)
notifier_app = Client(
    "notifier_bot",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)


async def _notify_me(lead: dict):
    username = lead.get("username")
    link = f"https://t.me/{username}" if username else f"tg://user?id={lead['user_id']}"
    text = (
        "🎯 <b>Новый лид</b>\n\n"
        f"<b>Кто:</b> {lead.get('name') or '—'} "
        f"({'@' + username if username else 'без username'})\n"
        f"<b>Ссылка:</b> {link}\n"
        f"<b>Чат:</b> {lead.get('chat_title') or '—'}\n\n"
        f"<b>Сообщение:</b>\n{lead['message']}\n\n"
        f"<b>Почему матч:</b>\n{lead['reason']}\n\n"
        f"<b>Черновик ответа:</b>\n<code>{lead['draft_reply']}</code>"
    )
    try:
        await notifier_app.send_message(MY_TELEGRAM_ID, text, parse_mode="html")
    except Exception as e:
        log.exception("Failed to notify: %s", e)


@user_app.on_message(filters.group & ~filters.service & ~filters.me)
async def on_group_message(_, message: Message):
    if not message.text:
        return
    chat = message.chat
    chat_uname = (chat.username or "").lower()
    if TARGET_GROUPS and chat_uname not in {g.lower() for g in TARGET_GROUPS}:
        return

    if not await mark_seen(chat.id, message.id):
        return

    # рандомная задержка перед обработкой (имитация человека)
    await asyncio.sleep(random.uniform(3, 7))

    user = message.from_user
    if not user or user.is_bot:
        return

    author = user.username or user.first_name or str(user.id)
    chat_title = chat.title or chat_uname

    result = await detect_lead(message.text, author, chat_title)
    if not result.get("match"):
        return

    lead = {
        "user_id": user.id,
        "username": user.username,
        "name": user.first_name,
        "chat_title": chat_title,
        "message": message.text,
        "reason": result.get("reason", ""),
        "draft_reply": result.get("draft_reply", ""),
    }
    await save_lead(**lead)
    await _notify_me(lead)
    log.info("Lead saved: %s", author)


async def run_monitor():
    await notifier_app.start()
    await user_app.start()
    log.info("Monitor started. Watching groups: %s", TARGET_GROUPS or "(all)")
    await asyncio.Event().wait()
