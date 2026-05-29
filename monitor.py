import asyncio
import logging
import random

from telethon import TelegramClient, events

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_GROUPS, SESSION_NAME,
    AUTO_REPLY_ENABLED, AUTO_REPLY_MIN_SCORE, AUTO_REPLY_PER_CHAT_DAY,
    AUTO_REPLY_DELAY_MIN, AUTO_REPLY_DELAY_MAX,
)
from claude_client import detect_lead
from db import (
    save_lead, mark_seen, get_lead, recent_lead_for_user,
    history_for_user, list_dynamic_chats,
    auto_replies_in_chat_24h, log_auto_reply,
)
from bot_handlers import send_lead_notification, send_auto_reply_notice

log = logging.getLogger(__name__)

user_client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)


async def _target_set() -> set[str]:
    static = {g.lower() for g in TARGET_GROUPS}
    dynamic = set(await list_dynamic_chats())
    return static | dynamic


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
    targets = await _target_set()
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

    # Анти-дубль: если уже был лид за последние 3 дня — не пушим повторно
    prev = await recent_lead_for_user(sender.id, days=3)
    if prev:
        log.info(
            "Skip duplicate lead from user_id=%s (prev id=%s within 3d)",
            sender.id, prev["id"],
        )
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
        score=int(result.get("score", 5)),
        temperature=result.get("temperature", "warm"),
        product_type=result.get("product_type", "custom"),
        intent=result.get("intent", "client"),
    )
    lead = await get_lead(lead_id)
    history = await history_for_user(sender.id, limit=5)
    lead["_history"] = [h for h in history if h["id"] != lead_id]
    await send_lead_notification(lead_id, lead)
    log.info("Lead saved id=%s author=%s score=%s", lead_id, author, lead.get("score"))

    # Авто-ответ в чат (вариант B) — только если включено и лид горячий
    asyncio.create_task(_maybe_auto_reply(event, lead_id, lead))


async def _maybe_auto_reply(event, lead_id: int, lead: dict):
    if not AUTO_REPLY_ENABLED:
        return
    score = lead.get("score") or 0
    if score < AUTO_REPLY_MIN_SCORE:
        log.info("Auto-reply skip lead=%s: score %s < %s", lead_id, score, AUTO_REPLY_MIN_SCORE)
        return

    chat_id = event.chat_id
    count = await auto_replies_in_chat_24h(chat_id)
    if count >= AUTO_REPLY_PER_CHAT_DAY:
        log.info("Auto-reply skip lead=%s: chat %s reached daily limit %s",
                 lead_id, chat_id, AUTO_REPLY_PER_CHAT_DAY)
        await send_auto_reply_notice(lead_id, "⚠️ Лимит авто-ответов в этом чате на сутки исчерпан, не отвечаю.")
        return

    draft = lead.get("draft_reply") or ""
    if not draft.strip():
        return

    delay = random.uniform(AUTO_REPLY_DELAY_MIN, AUTO_REPLY_DELAY_MAX)
    log.info("Auto-reply lead=%s: sending in %.0fs", lead_id, delay)
    await asyncio.sleep(delay)

    try:
        sent = await event.reply(draft)
        await log_auto_reply(lead_id, chat_id, sent.id, draft)
        await send_auto_reply_notice(
            lead_id,
            f"📤 <b>Авто-ответ отправлен в чат</b> (за сутки в этом чате: {count + 1}/{AUTO_REPLY_PER_CHAT_DAY})",
        )
        log.info("Auto-reply sent lead=%s msg_id=%s", lead_id, sent.id)
    except Exception as e:
        log.exception("Auto-reply failed lead=%s: %s", lead_id, e)
        await send_auto_reply_notice(lead_id, f"⚠️ Не смог отправить авто-ответ: {e}")


async def run_monitor():
    await user_client.start()
    # промо-механики (реакции на свой канал, комменты под конкурентами)
    try:
        from promo import register_own_channel_handler, register_competitor_handlers
        register_own_channel_handler(user_client)
        register_competitor_handlers(user_client)
        log.info("Promo handlers registered")
    except Exception as e:
        log.warning("Promo handlers not registered: %s", e)
    log.info("Monitor started. Watching groups: %s", TARGET_GROUPS or "(all)")
    await user_client.run_until_disconnected()
