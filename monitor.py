import asyncio
import logging
import random

from telethon import TelegramClient, events

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_GROUPS, SESSION_NAME,
)
from claude_client import detect_lead
from db import save_lead, mark_seen, get_lead
from bot_handlers import send_lead_notification

log = logging.getLogger(__name__)

user_client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)


def _target_set() -> set[str]:
    return {g.lower() for g in TARGET_GROUPS}


async def _fetch_context(chat, target_msg_id: int, limit: int = 5) -> list[dict]:
    """Берёт `limit` сообщений ДО целевого в том же чате, возвращает в хронологическом порядке."""
    result = []
    try:
        async for msg in user_client.iter_messages(chat, limit=limit, offset_id=target_msg_id):
            if not msg.message:
                continue
            try:
                s = await msg.get_sender()
                author = (s.username or s.first_name or str(s.id)) if s else "?"
            except Exception:
                author = "?"
            result.append({"author": author, "text": msg.message})
    except Exception as e:
        log.warning("Failed to fetch context: %s", e)
    return list(reversed(result))


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

    context = await _fetch_context(chat, event.id, limit=5)
    result = await detect_lead(event.message.message, author, chat_title, context=context)
    if not result.get("match"):
        return

    lead_id = await save_lead(
        user_id=sender.id,
        username=sender.username,
        name=sender.first_name,
        chat_title=chat_title,
        chat_id=event.chat_id,
        message=event.message.message,
        message_id=event.id,
        reason=result.get("reason", ""),
        draft_reply=result.get("draft_reply", ""),
    )
    lead = await get_lead(lead_id)
    await send_lead_notification(lead_id, lead)
    log.info("Lead saved id=%s author=%s", lead_id, author)


async def run_monitor():
    await user_client.start()
    log.info("Monitor started. Watching groups: %s", TARGET_GROUPS or "(all)")
    await user_client.run_until_disconnected()
