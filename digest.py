"""Утренний дайджест: каждый день в 9:00 по локальному времени сервера
шлёт владельцу сводку по лидам за последние 24 часа."""
import asyncio
import logging
from datetime import datetime, time, timedelta

from telegram.constants import ParseMode

from config import MY_TELEGRAM_ID
from db import leads_since

log = logging.getLogger(__name__)

SEND_AT = time(hour=9, minute=0)  # локальное время сервера


_STATUS_LABEL = {"new": "🆕", "contacted": "✅", "closed": "🎉", "not_lead": "❌"}
_TEMP_BADGE = {"hot": "🔥", "warm": "☕", "cold": "🧊"}


def _format_digest(leads: list[dict]) -> str:
    if not leads:
        return "☀️ <b>Дайджест за 24ч</b>\n\nЛидов не было."

    hot = [l for l in leads if (l.get("temperature") or "warm") == "hot"]
    warm = [l for l in leads if (l.get("temperature") or "warm") == "warm"]
    cold = [l for l in leads if (l.get("temperature") or "warm") == "cold"]
    new = sum(1 for l in leads if l["status"] == "new")
    contacted = sum(1 for l in leads if l["status"] == "contacted")

    lines = [
        f"☀️ <b>Дайджест за 24ч</b>",
        "",
        f"Всего лидов: <b>{len(leads)}</b>",
        f"🔥 hot: {len(hot)}   ☕ warm: {len(warm)}   🧊 cold: {len(cold)}",
        f"🆕 новых: {new}   ✅ обработано: {contacted}",
        "",
        "<b>Топ по горячести:</b>",
    ]
    for l in leads[:10]:
        uname = l.get("username")
        u = f"@{uname}" if uname else (l.get("name") or "—")
        badge = _TEMP_BADGE.get(l.get("temperature") or "warm", "☕")
        status = _STATUS_LABEL.get(l["status"], "")
        snippet = (l.get("message") or "").replace("\n", " ")[:80]
        lines.append(f"{badge} {l.get('score', 5)}/10 {status} {u} — «{snippet}»")
    return "\n".join(lines)


def _seconds_until_next(target: time) -> float:
    now = datetime.now()
    target_dt = now.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    if target_dt <= now:
        target_dt += timedelta(days=1)
    return (target_dt - now).total_seconds()


async def digest_loop(bot):
    while True:
        delay = _seconds_until_next(SEND_AT)
        log.info("Digest will fire in %.0f seconds", delay)
        await asyncio.sleep(delay)
        try:
            leads = await leads_since(hours=24)
            text = _format_digest(leads)
            await bot.send_message(
                chat_id=MY_TELEGRAM_ID, text=text, parse_mode=ParseMode.HTML
            )
            log.info("Digest sent (%s leads)", len(leads))
        except Exception as e:
            log.exception("Digest failed: %s", e)
        # Подстраховка: чтобы не отправить дважды если ушло за миллисекунды
        await asyncio.sleep(60)
