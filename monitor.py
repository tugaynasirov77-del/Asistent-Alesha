import asyncio
import logging
import random

from telethon import TelegramClient, events
from telegram import Bot
from telegram.constants import ParseMode

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_GROUPS,
    SESSION_NAME, MY_TELEGRAM_ID, BOT_TOKEN,
)
from claude_client import detect_lead
from db import save_lead, mark_seen

log = logging.getLogger(__name__)

user_client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
notifier_bot = Bot(token=BOT_TOKEN)


def _target_set() -> set[str]:
    return {g.lower() for g in TARGET_GROUPS}


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
        await notifier_bot.send_message(
            chat_id=MY_TELEGRAM_ID, text=text, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.exception("Failed to notify: %s", e)


@user_client.on(events.NewMessage(incoming=True))
async def on_message(event: events.NewMessage.Event):
    if not event.is_group and not event.is_channel:
        return
    if not event.message.message:
        return

    chat = await event.get_chat()
    chat_uname = (getattr(chat, "username", None) or "").lower()
    targets = _target_set()
    if targets and chat_uname not in targets:
        return

    if not await mark_seen(event.chat_id, event.id):
        return

    await asyncio.sleep(random.uniform(3, 7))

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return

    author = sender.username or sender.first_name or str(sender.id)
    chat_title = getattr(chat, "title", None) or chat_uname

    result = await detect_lead(event.message.message, author, chat_title)
    if not result.get("match"):
        return

    lead = {
        "user_id": sender.id,
        "username": sender.username,
        "name": sender.first_name,
        "chat_title": chat_title,
        "message": event.message.message,
        "reason": result.get("reason", ""),
        "draft_reply": result.get("draft_reply", ""),
    }
    await save_lead(**lead)
    await _notify_me(lead)
    log.info("Lead saved: %s", author)


async def run_monitor():
    await user_client.start()
    log.info("Monitor started. Watching groups: %s", TARGET_GROUPS or "(all)")
    await user_client.run_until_disconnected()
