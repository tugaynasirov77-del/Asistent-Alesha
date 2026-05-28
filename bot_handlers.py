"""Бот-уведомитель: рендерит лид с кнопками и обрабатывает их клики."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, ContextTypes,
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, MY_TELEGRAM_ID
from db import get_lead, update_lead_draft, update_lead_status
from claude_client import regenerate_draft

log = logging.getLogger(__name__)

_application: Application | None = None


_TEMP_BADGE = {"hot": "🔥 HOT", "warm": "☕ WARM", "cold": "🧊 COLD"}


def render_lead_text(lead: dict) -> str:
    username = lead.get("username")
    name = lead.get("name") or "—"
    chat_title = lead.get("chat_title") or "—"
    uname_str = f"@{username}" if username else "без username"
    temp = (lead.get("temperature") or "warm").lower()
    score = lead.get("score") or 5
    badge = _TEMP_BADGE.get(temp, "☕ WARM")
    return (
        f"🎯 <b>Новый лид</b>  {badge} <b>{score}/10</b>\n\n"
        f"<b>Кто:</b> {name} ({uname_str})\n"
        f"<b>Чат:</b> {chat_title}\n\n"
        f"<b>Сообщение:</b>\n{lead['message']}\n\n"
        f"<b>Почему матч:</b>\n{lead['reason']}\n\n"
        f"<b>Черновик ответа:</b>\n<i>{lead['draft_reply']}</i>"
    )


def lead_keyboard(lead_id: int, username: str | None, user_id: int) -> InlineKeyboardMarkup:
    profile_url = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Скопировать", callback_data=f"copy:{lead_id}"),
            InlineKeyboardButton("🔄 Другой", callback_data=f"regen:{lead_id}"),
        ],
        [
            InlineKeyboardButton("👤 Открыть профиль", url=profile_url),
        ],
        [
            InlineKeyboardButton("✅ Связался", callback_data=f"done:{lead_id}"),
            InlineKeyboardButton("❌ Не лид", callback_data=f"skip:{lead_id}"),
        ],
    ])


async def send_lead_notification(lead_id: int, lead: dict):
    """Шлёт уведомление о новом лиде владельцу."""
    if _application is None:
        log.error("Bot application not initialized")
        return
    await _application.bot.send_message(
        chat_id=MY_TELEGRAM_ID,
        text=render_lead_text(lead),
        parse_mode=ParseMode.HTML,
        reply_markup=lead_keyboard(lead_id, lead.get("username"), lead.get("user_id")),
    )


async def _on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data or ":" not in query.data:
        return
    action, sid = query.data.split(":", 1)
    try:
        lead_id = int(sid)
    except ValueError:
        return

    lead = await get_lead(lead_id)
    if not lead:
        await query.edit_message_text("⚠️ Лид не найден в базе.")
        return

    if action == "copy":
        # Шлём черновик отдельным сообщением — long-press копирует одним тапом
        await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"`{lead['draft_reply']}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if action == "regen":
        await query.edit_message_text("⏳ Генерирую другой вариант...")
        new_draft = await regenerate_draft(
            message_text=lead["message"],
            author=lead.get("username") or lead.get("name") or "—",
            chat_title=lead.get("chat_title") or "—",
            previous_draft=lead["draft_reply"],
            style="expert" if "?" in lead["draft_reply"] else "friendly",
        )
        await update_lead_draft(lead_id, new_draft)
        updated = await get_lead(lead_id)
        await query.edit_message_text(
            text=render_lead_text(updated),
            parse_mode=ParseMode.HTML,
            reply_markup=lead_keyboard(lead_id, updated.get("username"), updated.get("user_id")),
        )
        return

    if action == "done":
        await update_lead_status(lead_id, "contacted")
        await query.edit_message_text(
            text=render_lead_text(lead) + "\n\n✅ <b>Помечен как «связался»</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "skip":
        await update_lead_status(lead_id, "not_lead")
        await query.edit_message_text(
            text=render_lead_text(lead) + "\n\n❌ <b>Помечен как не лид</b>",
            parse_mode=ParseMode.HTML,
        )
        return


async def init_bot() -> Application:
    """С retry — сеть до api.telegram.org с RU-сервера часто лагает на старте."""
    import asyncio as _asyncio
    global _application
    last_err = None
    for attempt in range(1, 6):
        try:
            req = HTTPXRequest(connect_timeout=60, read_timeout=60, write_timeout=60, pool_timeout=60)
            app = (
                Application.builder()
                .token(BOT_TOKEN)
                .request(req)
                .get_updates_request(HTTPXRequest(connect_timeout=60, read_timeout=120))
                .build()
            )
            app.add_handler(CallbackQueryHandler(_on_callback))
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            _application = app
            log.info("Notifier bot started (attempt %s)", attempt)
            return app
        except Exception as e:
            last_err = e
            log.warning("Bot init attempt %s failed: %s", attempt, e)
            await _asyncio.sleep(5 * attempt)
    raise RuntimeError(f"Bot init failed after 5 attempts: {last_err}")


async def shutdown_bot(app: Application):
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
