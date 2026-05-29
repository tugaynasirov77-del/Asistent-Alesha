"""Промо-механики через userbot:
- profile_promo: ставит имя/био с упоминанием канала (один раз)
- react_to_own_channel: реагирует на новые посты @daniil_prim
- smart_comment_on_competitors: пишет экспертные комменты под постами каналов из watch-листа
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Iterable

from telethon import events
from telethon.errors import RPCError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.types import ReactionEmoji

from claude_client import client as ai_client, MODEL

log = logging.getLogger(__name__)

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "daniil_prim")
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

PROFILE_FIRST_NAME = os.getenv("PROFILE_FIRST_NAME", "Даниил")
PROFILE_LAST_NAME = os.getenv("PROFILE_LAST_NAME", "| AI-автоматизация")
PROFILE_BIO = os.getenv(
    "PROFILE_BIO",
    f"Делаю AI-агентов и автоматизирую бизнес. Кейсы → t.me/{CHANNEL_USERNAME}",
)

REACTIONS = ["🔥", "❤️", "👍", "💯", "🤯"]

# Каналы конкурентов/смежные — где сидит ЦА. Управляются через /comp_add /comp_remove
COMPETITORS: set[str] = set()

# вкл/выкл механик (можно гонять командами)
PROMO_FLAGS = {
    "react_own": True,
    "comment_competitors": False,  # выкл по умолчанию — включать осознанно
}


# ─── (а) Профиль ─────────────────────────────────────────────────────

async def apply_profile_promo(user_client) -> str:
    try:
        await user_client(UpdateProfileRequest(
            first_name=PROFILE_FIRST_NAME,
            last_name=PROFILE_LAST_NAME,
            about=PROFILE_BIO[:70],  # Telegram лимит био ~70 символов
        ))
        return (
            f"✅ Профиль обновлён:\n"
            f"Имя: {PROFILE_FIRST_NAME} {PROFILE_LAST_NAME}\n"
            f"Био: {PROFILE_BIO[:70]}"
        )
    except RPCError as e:
        return f"⚠️ Не удалось обновить профиль: {e}"


# ─── (в) Reaction farming на своих постах ────────────────────────────

async def react_to_own_post(user_client, message):
    if not PROMO_FLAGS["react_own"]:
        return
    try:
        emoji = random.choice(REACTIONS)
        # имитация: задержка перед реакцией
        await asyncio.sleep(random.uniform(45, 180))
        await user_client.send_message(
            entity=message.chat_id,
            message="",  # not used
        ) if False else None  # placeholder
        # Telethon API для реакции:
        from telethon.tl.functions.messages import SendReactionRequest
        await user_client(SendReactionRequest(
            peer=await message.get_chat(),
            msg_id=message.id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
        log.info("Reacted %s on @%s post %s", emoji, CHANNEL_USERNAME, message.id)
    except Exception as e:
        log.warning("React failed: %s", e)


def register_own_channel_handler(user_client):
    """Подписаться на новые посты собственного канала."""
    @user_client.on(events.NewMessage(chats=CHANNEL_USERNAME))
    async def _h(event):
        await react_to_own_post(user_client, event.message)


# ─── (б) Smart-комментарии под постами конкурентов ───────────────────

_COMMENT_PROMPT = """Ты — эксперт по AI-автоматизации (от лица Тугая Насирова, @prim_daniil).
Под постом в Telegram-канале нужно написать ЭКСПЕРТНЫЙ комментарий, который:
- Даёт реальную пользу (факт, цифра, нюанс, отсылка к опыту) — не повторяет пост
- Не выглядит рекламой
- 1-3 предложения максимум, без эмодзи-спама
- Звучит как живой эксперт, не как маркетолог

В 20% случаев ТОНКО упоминай свой канал t.me/{ch} в конце ("у себя в канале как раз
разбирал..." / "подробнее у меня"). В остальных 80% — без упоминаний, чистая польза.

Тема канала: AI, бизнес-автоматизация, IT, no-code.
"""


async def _generate_comment(post_text: str, mention_chance: float = 0.2) -> str | None:
    mention = random.random() < mention_chance
    prompt = _COMMENT_PROMPT.format(ch=CHANNEL_USERNAME)
    if mention:
        prompt += "\n\nВ ЭТОТ раз — обязательно упомяни канал в конце."
    else:
        prompt += "\n\nВ ЭТОТ раз — БЕЗ упоминания канала."
    try:
        resp = await ai_client.messages.create(
            model=MODEL, max_tokens=300,
            system=prompt,
            messages=[{"role": "user", "content": f"Пост:\n{post_text[:1500]}"}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return text.strip()
    except Exception as e:
        log.exception("Comment gen failed: %s", e)
        return None


async def comment_on_competitor_post(user_client, event):
    if not PROMO_FLAGS["comment_competitors"]:
        return
    post_text = event.message.message or ""
    if len(post_text) < 30:
        return
    text = await _generate_comment(post_text)
    if not text:
        return
    try:
        await asyncio.sleep(random.uniform(60, 240))  # имитация чтения
        await user_client.send_message(
            entity=event.chat_id,
            message=text,
            comment_to=event.message.id,
        )
        log.info("Smart comment posted under @%s/%s",
                 getattr(event.chat, 'username', '?'), event.message.id)
    except Exception as e:
        log.warning("Smart comment failed: %s", e)


def register_competitor_handlers(user_client):
    """Хендлер слушает новые сообщения в каналах из COMPETITORS."""
    @user_client.on(events.NewMessage())
    async def _h(event):
        chat = await event.get_chat()
        uname = (getattr(chat, "username", None) or "").lower()
        if uname in {c.lower() for c in COMPETITORS}:
            await comment_on_competitor_post(user_client, event)
