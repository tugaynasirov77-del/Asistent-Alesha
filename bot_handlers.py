"""Бот-уведомитель: рассылает лиды всем подписчикам, обрабатывает кнопки."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, MY_TELEGRAM_ID
from db import (
    get_lead, update_lead_draft, update_lead_status,
    add_subscriber, all_subscribers, remove_subscriber,
)
from claude_client import regenerate_draft

log = logging.getLogger(__name__)

_application: Application | None = None


_TEMP_BADGE = {"hot": "🔥 ГОРЯЧИЙ", "warm": "☕ ТЁПЛЫЙ", "cold": "🧊 ХОЛОДНЫЙ"}
_STATUS_LABEL = {
    "new": "🆕 не отвечал",
    "contacted": "✅ связался",
    "closed": "🎉 закрыт",
    "not_lead": "❌ не лид",
}


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["", "<b>📌 Был раньше:</b>"]
    for h in history[:3]:
        status = _STATUS_LABEL.get(h["status"], h["status"])
        snippet = (h.get("message") or "").replace("\n", " ")[:60]
        date = (h.get("created_at") or "")[:10]
        chat = h.get("chat_title") or "—"
        lines.append(f"• {date} [{chat}] {status} — «{snippet}»")
    return "\n".join(lines)


def render_lead_text(lead: dict) -> str:
    username = lead.get("username")
    name = lead.get("name") or "—"
    chat_title = lead.get("chat_title") or "—"
    uname_str = f"@{username}" if username else "без username"
    temp = (lead.get("temperature") or "warm").lower()
    score = lead.get("score") or 5
    badge = _TEMP_BADGE.get(temp, "☕ ТЁПЛЫЙ")
    history_block = _format_history(lead.get("_history") or [])
    return (
        f"🎯 <b>Новый лид</b>  {badge} <b>{score}/10</b>\n\n"
        f"<b>Кто:</b> {name} ({uname_str})\n"
        f"<b>Чат:</b> {chat_title}\n\n"
        f"<b>Сообщение:</b>\n{lead['message']}\n\n"
        f"<b>Почему матч:</b>\n{lead['reason']}\n\n"
        f"<b>Черновик ответа:</b>\n<i>{lead['draft_reply']}</i>"
        f"{history_block}"
    )


def lead_keyboard(lead_id: int, username: str | None, user_id: int) -> InlineKeyboardMarkup:
    profile_url = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Скопировать", callback_data=f"copy:{lead_id}"),
            InlineKeyboardButton("🔄 Другой", callback_data=f"regen:{lead_id}"),
        ],
        [InlineKeyboardButton("👤 Открыть профиль", url=profile_url)],
        [
            InlineKeyboardButton("✅ Связался", callback_data=f"done:{lead_id}"),
            InlineKeyboardButton("❌ Не лид", callback_data=f"skip:{lead_id}"),
        ],
    ])


async def _broadcast(text: str, parse_mode=ParseMode.HTML, reply_markup=None):
    """Шлёт сообщение всем подписчикам + владельцу."""
    if _application is None:
        log.error("Bot application not initialized")
        return
    ids = set(await all_subscribers())
    ids.add(MY_TELEGRAM_ID)  # владелец всегда получает
    for chat_id in ids:
        try:
            await _application.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=parse_mode, reply_markup=reply_markup,
            )
        except Exception as e:
            log.warning("Broadcast failed for %s: %s", chat_id, e)


async def send_lead_notification(lead_id: int, lead: dict):
    await _broadcast(
        text=render_lead_text(lead),
        reply_markup=lead_keyboard(lead_id, lead.get("username"), lead.get("user_id")),
    )


async def broadcast_digest(text: str):
    await _broadcast(text=text)


async def _on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    is_new = await add_subscriber(chat.id, user.username, user.first_name)
    if is_new:
        await update.message.reply_text(
            "✅ Подписан на уведомления о лидах.\n"
            "Каждый раз когда в одном из мониторимых чатов появится потенциальный клиент — "
            "тебе придёт уведомление с готовым черновиком ответа."
        )
    else:
        await update.message.reply_text("✅ Ты уже подписан, новые лиды будут приходить сюда.")


async def _on_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    await remove_subscriber(chat.id)
    await update.message.reply_text("🔕 Отписан от уведомлений. Чтобы вернуться — /start.")


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
            app.add_handler(CommandHandler("start", _on_start))
            app.add_handler(CommandHandler("stop", _on_stop))
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
