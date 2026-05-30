"""Бот-уведомитель: лиды, команды управления, рассылка подписчикам."""
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, MY_TELEGRAM_ID, TARGET_GROUPS
from db import (
    get_lead, update_lead_draft, update_lead_status,
    add_subscriber, all_subscribers, remove_subscriber,
    leads_since, lead_stats,
    add_dynamic_chat, remove_dynamic_chat, list_dynamic_chats,
    list_unjoined_chats, mark_chat_joined,
)
from claude_client import regenerate_draft

log = logging.getLogger(__name__)

_application: Application | None = None

_TEMP_BADGE = {"hot": "🔥 ГОРЯЧИЙ", "warm": "☕ ТЁПЛЫЙ", "cold": "🧊 ХОЛОДНЫЙ"}
_TEMP_SHORT = {"hot": "🔥", "warm": "☕", "cold": "🧊"}
_STATUS_LABEL = {
    "new": "🆕 не отвечал",
    "contacted": "✅ связался",
    "closed": "🎉 закрыт",
    "not_lead": "❌ не лид",
}
_PRODUCT_BADGE = {
    "liva": "🏪 LIVA",
    "custom": "🛠 КАСТОМ",
    "both": "🎯 ОБА",
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
    product = (lead.get("product_type") or "custom").lower()
    intent = (lead.get("intent") or "client").lower()
    badge = _TEMP_BADGE.get(temp, "☕ ТЁПЛЫЙ")
    product_badge = _PRODUCT_BADGE.get(product, "🛠 КАСТОМ")
    urgent = "🚨🚨🚨 СРОЧНО! 🚨🚨🚨\n\n" if score >= 10 else ""
    history_block = _format_history(lead.get("_history") or [])

    if intent == "channel_invite":
        title = "📣 <b>Кандидат в канал</b>"
        meta = f"{badge} <b>{score}/10</b>"
    else:
        title = "🎯 <b>Новый лид</b>"
        meta = f"{badge} <b>{score}/10</b>  {product_badge}"

    return (
        f"{urgent}{title}  {meta}\n\n"
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


async def _broadcast(text: str, parse_mode=ParseMode.HTML, reply_markup=None,
                     disable_notification: bool = False):
    if _application is None:
        log.error("Bot application not initialized")
        return
    ids = set(await all_subscribers())
    ids.add(MY_TELEGRAM_ID)
    for chat_id in ids:
        try:
            await _application.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=parse_mode, reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
        except Exception as e:
            log.warning("Broadcast failed for %s: %s", chat_id, e)


async def send_lead_notification(lead_id: int, lead: dict):
    # Горячие лиды (score 9-10) — со звуком, остальные молча
    score = lead.get("score") or 5
    urgent = score >= 9
    await _broadcast(
        text=render_lead_text(lead),
        reply_markup=lead_keyboard(lead_id, lead.get("username"), lead.get("user_id")),
        disable_notification=not urgent,
    )


async def broadcast_digest(text: str):
    await _broadcast(text=text)


async def send_auto_reply_notice(lead_id: int, text: str):
    """Шлёт всем подписчикам короткое уведомление об авто-ответе для конкретного лида."""
    await _broadcast(text=f"Лид #{lead_id}\n{text}")


# ─── команды ──────────────────────────────────────────────────────────

async def _on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    is_new = await add_subscriber(chat.id, user.username, user.first_name)
    if is_new:
        await update.message.reply_text(
            "✅ Подписан на уведомления о лидах.\n\n"
            "Команды:\n"
            "/leads — последние 10 лидов\n"
            "/leads hot — только горячие\n"
            "/stats — статистика за сегодня/неделю/месяц\n"
            "/chats — список мониторимых чатов\n"
            "/add username — добавить чат\n"
            "/remove username — убрать чат\n"
            "/stop — отписаться"
        )
    else:
        await update.message.reply_text("Ты уже подписан. /help — список команд.")


async def _on_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import config as _cfg
    auto = "вкл ✅" if _cfg.AUTO_REPLY_ENABLED else "выкл ❌"
    await update.message.reply_text(
        f"Команды:\n"
        f"/leads [hot|warm|cold] — последние 10 лидов\n"
        f"/stats — статистика 24ч / 7д / 30д\n"
        f"/chats — мониторимые чаты\n"
        f"/add username — добавить чат\n"
        f"/remove username — убрать чат\n"
        f"/autoreply on|off — авто-ответы в чаты (сейчас: {auto})\n"
        f"\nПромо канала @daniil_prim:\n"
        f"/setprofile — обновить имя/био твоего @prim_daniil (реклама канала)\n"
        f"/react on|off — авто-реакции на свои посты (для виральности)\n"
        f"/comp add username — добавить чужой канал для smart-комментариев\n"
        f"/comp on|off — включить/выключить написание комментариев\n"
        f"\n/stop — отписаться"
    )


async def _do_discover(update, ctx, kind: str):
    """Общий хелпер: kind = 'chats' | 'channels' | 'both'."""
    from monitor import user_client
    from discovery import discover_candidates, CHAT_PACKS, CHANNEL_PACKS

    packs_map = CHANNEL_PACKS if kind == "channels" else CHAT_PACKS
    pack = (ctx.args[0].lower() if ctx.args else "beauty")
    if pack not in packs_map:
        await update.message.reply_text(
            "Доступные ниши:\n" + "\n".join(f"• {p}" for p in packs_map)
        )
        return

    label = {"chats": "ЧАТЫ", "channels": "КАНАЛЫ", "both": "каналы и чаты"}[kind]
    await update.message.reply_text(
        f"🔍 Ищу {label} в нише «{pack}»... 30-60 секунд."
    )
    try:
        candidates = await discover_candidates(user_client, pack, kind=kind, max_results=10)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка поиска: {e}")
        return

    if not candidates:
        await update.message.reply_text(
            f"Ничего нового не нашёл в нише «{pack}». "
            f"Попробуй другую: services / automation / selfworkers"
        )
        return

    await update.message.reply_text(f"Нашёл {len(candidates)} кандидатов:")
    for c in candidates:
        kind_emoji = "📺 канал" if c["is_channel"] else ("💬 чат" if c["is_megagroup"] else "❓")
        text = (
            f"{kind_emoji} <b>{c['title']}</b>\n"
            f"@{c['username']}  ·  {c['participants_count']:,} участников\n"
            f"Найден по запросу: «{c['matched_query']}»"
        )
        kb_rows = []
        if c["is_channel"]:
            kb_rows.append([
                InlineKeyboardButton("➕ В комменты (smart)", callback_data=f"dca:{c['username']}"),
                InlineKeyboardButton("👁 Открыть", url=f"https://t.me/{c['username']}"),
            ])
        else:
            kb_rows.append([
                InlineKeyboardButton("➕ В мониторинг чатов", callback_data=f"dct:{c['username']}"),
                InlineKeyboardButton("👁 Открыть", url=f"https://t.me/{c['username']}"),
            ])
        kb_rows.append([InlineKeyboardButton("❌ Скип", callback_data=f"dcx:{c['username']}")])
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb_rows),
        )


async def _on_discover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Общий поиск (чаты + каналы)."""
    await _do_discover(update, ctx, kind="both")


async def _on_findchannels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Поиск ТОЛЬКО каналов для smart-комментариев."""
    await _do_discover(update, ctx, kind="channels")


async def _on_findchats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Поиск ТОЛЬКО чатов для мониторинга лидов."""
    await _do_discover(update, ctx, kind="chats")


async def _on_joinall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Userbot вступает во все dynamic_chats где ещё не состоит.
    С задержкой 40-90 секунд между чатами, чтобы Telegram не заподозрил массовый join."""
    import asyncio as _asyncio
    import random as _random
    from monitor import user_client
    from telethon.errors import (
        ChannelsTooMuchError, UserAlreadyParticipantError, ChannelPrivateError,
        InviteRequestSentError, FloodWaitError, UsernameInvalidError, UsernameNotOccupiedError,
    )
    chats = await list_unjoined_chats()
    total_known = len(await list_dynamic_chats())
    if not chats:
        await update.message.reply_text(
            f"✨ Все {total_known} чатов уже отмечены как «вступил». "
            f"Если ты ВРУЧНУЮ вступил в новые после /joinall — просто добавь их "
            f"через /add username, либо /discover.\n\n"
            f"Принудительно проверить заново можно через /joinall_force"
        )
        return
    await update.message.reply_text(
        f"Начинаю вступать в {len(chats)} НОВЫХ чатов "
        f"(из {total_known} в БД, остальные уже отмечены).\n"
        f"Пауза 40-90с между ними. Отчёт по ходу."
    )
    joined, already, skipped, errors = 0, 0, 0, 0
    for i, uname in enumerate(chats, 1):
        try:
            entity = await user_client.get_entity(uname)
            await user_client(__import__(
                "telethon.tl.functions.channels", fromlist=["JoinChannelRequest"]
            ).JoinChannelRequest(entity))
            await mark_chat_joined(uname)
            joined += 1
            status = "✅ вступил"
        except UserAlreadyParticipantError:
            await mark_chat_joined(uname)  # запомним чтобы не дёргать снова
            already += 1
            status = "ℹ️ уже состоит — отметил"
        except (UsernameInvalidError, UsernameNotOccupiedError, ChannelPrivateError) as e:
            skipped += 1
            status = f"⏭ пропущен ({type(e).__name__})"
        except FloodWaitError as e:
            await update.message.reply_text(
                f"⚠️ FloodWait {e.seconds}с. Останавливаюсь на @{uname}. "
                f"Запусти /joinall ещё раз — пойдёт с того же места."
            )
            return
        except Exception as e:
            errors += 1
            status = f"❌ ошибка: {e}"
        await update.message.reply_text(f"[{i}/{len(chats)}] @{uname}: {status}")
        if i < len(chats):
            await _asyncio.sleep(_random.uniform(40, 90))
    await update.message.reply_text(
        f"🏁 Готово.\nВступил: {joined}\nУже состоял (отметил): {already}\n"
        f"Пропущен: {skipped}\nОшибки: {errors}"
    )


async def _on_setprofile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Один раз обновить имя/био userbot аккаунта на промо-вариант."""
    try:
        from monitor import user_client
        from promo import apply_profile_promo
        result = await apply_profile_promo(user_client)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def _on_comp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Управление списком каналов конкурентов для smart-комментариев."""
    from promo import COMPETITORS, PROMO_FLAGS
    if not ctx.args:
        items = sorted(COMPETITORS) or ["(пусто)"]
        flag = "вкл ✅" if PROMO_FLAGS["comment_competitors"] else "выкл ❌"
        await update.message.reply_text(
            "Smart-комментарии под чужими каналами:\n"
            f"Состояние: {flag}\n\n"
            "Список:\n" + "\n".join(f"• {c}" for c in items) + "\n\n"
            "/comp add username — добавить\n"
            "/comp remove username — убрать\n"
            "/comp on  — включить авто-комменты\n"
            "/comp off — выключить"
        )
        return
    cmd = ctx.args[0].lower()
    if cmd == "add" and len(ctx.args) >= 2:
        u = ctx.args[1].lstrip("@").lower()
        COMPETITORS.add(u)
        await update.message.reply_text(f"✅ Добавлен @{u}. Состою ли я в нём — проверь сам.")
    elif cmd == "remove" and len(ctx.args) >= 2:
        u = ctx.args[1].lstrip("@").lower()
        COMPETITORS.discard(u)
        await update.message.reply_text(f"✅ Убран @{u}.")
    elif cmd == "on":
        PROMO_FLAGS["comment_competitors"] = True
        await update.message.reply_text("✅ Smart-комментарии включены.")
    elif cmd == "off":
        PROMO_FLAGS["comment_competitors"] = False
        await update.message.reply_text("❌ Smart-комментарии выключены.")
    else:
        await update.message.reply_text("Неизвестная команда. /comp — справка.")


async def _on_react(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from promo import PROMO_FLAGS, CHANNEL_USERNAME
    arg = (ctx.args[0].lower() if ctx.args else None)
    if arg == "on":
        PROMO_FLAGS["react_own"] = True
        await update.message.reply_text(f"✅ Авто-реакции на посты @{CHANNEL_USERNAME} включены.")
    elif arg == "off":
        PROMO_FLAGS["react_own"] = False
        await update.message.reply_text("❌ Авто-реакции выключены.")
    else:
        cur = "вкл ✅" if PROMO_FLAGS["react_own"] else "выкл ❌"
        await update.message.reply_text(
            f"Авто-реакции на @{CHANNEL_USERNAME}: {cur}\n"
            "Использование: /react on  или  /react off"
        )


async def _on_autoreply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import config as _cfg
    arg = (ctx.args[0].lower() if ctx.args else None)
    if arg == "on":
        _cfg.AUTO_REPLY_ENABLED = True
        await update.message.reply_text("✅ Авто-ответы включены (применится мгновенно).")
    elif arg == "off":
        _cfg.AUTO_REPLY_ENABLED = False
        await update.message.reply_text("❌ Авто-ответы выключены.")
    else:
        cur = "вкл ✅" if _cfg.AUTO_REPLY_ENABLED else "выкл ❌"
        await update.message.reply_text(
            f"Сейчас авто-ответы: {cur}\n"
            f"Использование: /autoreply on  или  /autoreply off"
        )


async def _on_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    await remove_subscriber(chat.id)
    await update.message.reply_text("🔕 Отписан. Чтобы вернуться — /start.")


async def _on_leads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    arg = (ctx.args[0].lower() if ctx.args else None)
    leads = await leads_since(hours=24 * 30)  # последний месяц
    if arg in {"hot", "warm", "cold"}:
        leads = [l for l in leads if (l.get("temperature") or "warm") == arg]
    leads = leads[:10]
    if not leads:
        await update.message.reply_text("Лидов пока нет.")
        return
    lines = [f"<b>📋 Последние {len(leads)} лидов:</b>\n"]
    for l in leads:
        u = f"@{l['username']}" if l.get("username") else (l.get("name") or "—")
        temp = _TEMP_SHORT.get(l.get("temperature") or "warm", "☕")
        status = _STATUS_LABEL.get(l["status"], "")
        product = _PRODUCT_BADGE.get(l.get("product_type") or "custom", "🛠")
        snippet = (l.get("message") or "").replace("\n", " ")[:60]
        date = (l.get("created_at") or "")[:10]
        lines.append(f"{temp} {l.get('score', 5)}/10 {product} {status} {u}\n  «{snippet}»  ({date})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _on_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s24 = await lead_stats(24)
    s7d = await lead_stats(24 * 7)
    s30d = await lead_stats(24 * 30)

    def _block(title, s):
        return (
            f"<b>{title}</b>: {s['total']} лидов\n"
            f"  🔥 {s['hot']}  ☕ {s['warm']}  🧊 {s['cold']}\n"
            f"  🏪 Liva: {s['liva']}   🛠 Кастом: {s['custom']}   🎯 Оба: {s['both']}\n"
            f"  ✅ связался: {s['contacted']}   🎉 закрыто: {s['closed']}"
        )

    text = "\n\n".join([
        "📊 <b>Статистика</b>",
        _block("За 24 часа", s24),
        _block("За 7 дней", s7d),
        _block("За 30 дней", s30d),
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def _on_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    static = sorted(TARGET_GROUPS)
    dynamic = sorted(await list_dynamic_chats())
    lines = ["<b>📡 Мониторимые чаты:</b>", ""]
    if static:
        lines.append("<b>Статичные (из config):</b>")
        for s in static:
            lines.append(f"• {s}")
    if dynamic:
        lines.append("")
        lines.append("<b>Динамичные (добавлены через бот):</b>")
        for d in dynamic:
            lines.append(f"• {d}")
    lines.append("")
    lines.append(f"Всего: {len(static) + len(dynamic)} чатов")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _on_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /add username  (без @)")
        return
    uname = ctx.args[0].lstrip("@").lower()
    user_id = update.effective_user.id if update.effective_user else 0
    ok = await add_dynamic_chat(uname, user_id)
    if ok:
        await update.message.reply_text(
            f"✅ Чат @{uname} добавлен. Userbot увидит его после следующего сообщения "
            f"(а ты сам должен в нём состоять)."
        )
    else:
        await update.message.reply_text(f"⚠️ Чат @{uname} уже в списке.")


async def _on_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /remove username")
        return
    uname = ctx.args[0].lstrip("@").lower()
    ok = await remove_dynamic_chat(uname)
    if ok:
        await update.message.reply_text(f"✅ Чат @{uname} удалён из мониторинга.")
    else:
        await update.message.reply_text(
            f"⚠️ Чат @{uname} не найден среди динамичных. "
            f"(Статичные из config — там не удалить.)"
        )


# ─── callbacks от кнопок в уведомлениях ────────────────────────────────

async def _on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data or ":" not in query.data:
        return
    action, sid = query.data.split(":", 1)

    # discovery callbacks — sid это username, не lead_id
    if action in {"dca", "dct", "dcx"}:
        uname = sid.lower()
        if action == "dca":
            from promo import COMPETITORS
            COMPETITORS.add(uname)
            await query.edit_message_text(
                f"✅ @{uname} добавлен в smart-комменты.\n"
                f"Активировать: /comp on"
            )
        elif action == "dct":
            from db import add_dynamic_chat
            await add_dynamic_chat(uname, 0)
            await query.edit_message_text(
                f"✅ @{uname} добавлен в мониторинг чатов.\n"
                f"Не забудь вступить: /joinall"
            )
        else:
            await query.edit_message_text(f"⏭ @{uname} пропущен")
        return

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


async def init_bot_forever() -> Application:
    """Бесконечный retry — сеть до api.telegram.org с RU-сервера часто лагает.
    Не падает: ждёт сколько надо, попутно даёт работать монитору."""
    import asyncio as _asyncio
    global _application
    attempt = 0
    while True:
        attempt += 1
        try:
            req = HTTPXRequest(connect_timeout=60, read_timeout=60, write_timeout=60, pool_timeout=60)
            builder = (
                Application.builder()
                .token(BOT_TOKEN)
                .request(req)
                .get_updates_request(HTTPXRequest(connect_timeout=60, read_timeout=120))
            )
            tg_proxy = os.getenv("TG_PROXY_BASE", "").rstrip("/")
            if tg_proxy:
                builder = builder.base_url(f"{tg_proxy}/bot").base_file_url(f"{tg_proxy}/file/bot")
                log.info("Bot API через прокси: %s", tg_proxy)
            app = builder.build()
            app.add_handler(CommandHandler("start", _on_start))
            app.add_handler(CommandHandler("help", _on_help))
            app.add_handler(CommandHandler("stop", _on_stop))
            app.add_handler(CommandHandler("leads", _on_leads))
            app.add_handler(CommandHandler("stats", _on_stats))
            app.add_handler(CommandHandler("chats", _on_chats))
            app.add_handler(CommandHandler("add", _on_add))
            app.add_handler(CommandHandler("remove", _on_remove))
            app.add_handler(CommandHandler("autoreply", _on_autoreply))
            app.add_handler(CommandHandler("setprofile", _on_setprofile))
            app.add_handler(CommandHandler("joinall", _on_joinall))
            app.add_handler(CommandHandler("discover", _on_discover))
            app.add_handler(CommandHandler("findchannels", _on_findchannels))
            app.add_handler(CommandHandler("findchats", _on_findchats))
            app.add_handler(CommandHandler("comp", _on_comp))
            app.add_handler(CommandHandler("react", _on_react))
            app.add_handler(CallbackQueryHandler(_on_callback))
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            _application = app
            log.info("Notifier bot started (attempt %s)", attempt)
            return app
        except Exception as e:
            log.warning("Bot init attempt %s failed: %s — retry in 60s", attempt, e)
            await _asyncio.sleep(60)


# обратная совместимость
init_bot = init_bot_forever


async def shutdown_bot(app: Application):
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
