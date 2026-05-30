"""Проактивный постинг в чатах: Алёша сам инициирует сообщения как живой участник.

Цель: повысить узнаваемость @prim_daniil в чатах ЦА. Когда подписчики увидят
его профиль — попадут на канал @livaai (через био).

Стратегия:
- Раз в час (~) выбираем случайный чат из dynamic_chats, где Алёша состоит
- Если в нём за сутки было меньше PROACTIVE_PER_CHAT_DAY постов от Алёши — постим
- Между постами в одном чате — пауза не меньше PROACTIVE_MIN_HOURS_BETWEEN часов
- Время суток случайное (учитываем что не ночью)
- Сообщение генерит Claude в живом разговорном стиле
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime

from claude_client import client as ai_client, MODEL_FAST

log = logging.getLogger(__name__)

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "livaai")

PROACTIVE_PROMPT = f"""Ты — Даниил Прим (@prim_daniil), фаундер AI-сервиса Liva ai
(ailiva.ru) для мастеров и малого бизнеса. Состоишь в Telegram-чате как обычный
участник — мастер/специалист, который тоже работает руками и понимает их боли.

Тебе нужно написать сообщение в этот чат. Цель — выглядеть как ПОЛЕЗНЫЙ ЖИВОЙ
УЧАСТНИК сообщества, а не маркетолог. Никто не должен заподозрить, что это бот.

ЖЁСТКИЕ правила:
- Максимум 1-2 коротких предложения (15-30 слов)
- Никаких эмодзи в начале/конце
- Никаких 'Привет всем!', 'Доброе утро', 'Коллеги!'
- Никаких !!! и КАПСА
- Разговорный стиль: маленькая буква в начале можно, без точки в конце можно
- Конкретика: цифра, личный опыт, нюанс — не общие фразы
- НЕ постить рекламу, не звать на ailiva.ru, не пиарить @{CHANNEL_USERNAME}

Тип сообщения (выбери уместный для контекста чата):
1. Личная история/опыт: "месяц назад начала вести запись через бот, выручка +30к"
2. Вопрос коллегам: "у кого админ есть? как платите ему за выходные?"
3. Размышление/наблюдение: "47% записи теперь приходит после 19 — раньше думала это вечерники"
4. Совет (без рекламы): "у меня сработало записывать в excel по сменам — потом легко смотреть"
5. Жалоба/боль: "опять забыла напомнить клиентке — не пришла. третий раз за месяц"

ПЛОХО (палится):
"Привет, коллеги! Делюсь крутым AI-сервисом ailiva.ru, он помогает с записью клиентов 🚀"

ХОРОШО (живо):
"девочки, у кого в субботу до полуночи пишут — отвечаете или забиваете?"

или:
"подскажите бота нормального для напоминаний, а то я задолбала забывать"

или:
"раз в неделю теряю клиента из-за того что не успеваю ответить. кошмар"

Тема чата: {{chat_title}}
Контекст последних сообщений: {{context}}

Верни ТОЛЬКО текст сообщения, без кавычек и пояснений.
"""


async def _generate_proactive_message(chat_title: str, context_msgs: list[str]) -> str | None:
    ctx_block = "\n".join(f"- {m}" for m in context_msgs[-5:]) if context_msgs else "(нет контекста)"
    prompt = PROACTIVE_PROMPT.format(chat_title=chat_title, context=ctx_block)
    try:
        resp = await ai_client.messages.create(
            model=MODEL_FAST,
            max_tokens=200,
            system=prompt,
            messages=[{"role": "user", "content": "Напиши сообщение."}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        # уберём кавычки если Claude всё-таки добавил
        text = text.strip('"«»“”').strip()
        return text or None
    except Exception as e:
        log.exception("Proactive generation failed: %s", e)
        return None


async def proactive_loop(user_client):
    """Главный цикл: ежедневно постит в каждый чат по 1 разу со случайными паузами
    в дневное окно. Минимальный гэп между ANY двумя постами — чтобы Telegram не палил."""
    from datetime import timedelta
    import config as _cfg
    from db import (
        list_dynamic_chats, proactive_posts_in_chat_24h,
    )

    log.info("Proactive loop started")
    while True:
        try:
            if not _cfg.PROACTIVE_ENABLED:
                await asyncio.sleep(300)
                continue

            now = datetime.now()
            start_h = _cfg.PROACTIVE_DAY_START_H
            end_h = _cfg.PROACTIVE_DAY_END_H

            # за окном дня — спим до утра
            if now.hour < start_h:
                next_run = now.replace(hour=start_h, minute=random.randint(0, 30),
                                       second=0, microsecond=0)
                wait = (next_run - now).total_seconds()
                log.info("Proactive: ночь, сплю до %s (%.0f мин)", next_run, wait / 60)
                await asyncio.sleep(wait)
                continue
            if now.hour >= end_h:
                tomorrow = now + timedelta(days=1)
                next_run = tomorrow.replace(hour=start_h, minute=random.randint(0, 30),
                                            second=0, microsecond=0)
                wait = (next_run - now).total_seconds()
                log.info("Proactive: уже вечер, сплю до %s (%.0f мин)", next_run, wait / 60)
                await asyncio.sleep(wait)
                continue

            # все известные чаты
            chats = await list_dynamic_chats()
            if not chats:
                await asyncio.sleep(1800)
                continue

            # отфильтруем те где сегодня уже постили
            pending: list[str] = []
            for u in chats:
                cnt = await proactive_posts_in_chat_24h(u)
                if cnt < _cfg.PROACTIVE_PER_CHAT_DAY:
                    pending.append(u)

            if not pending:
                # все на сегодня сделаны — спим до завтра
                tomorrow = now + timedelta(days=1)
                next_run = tomorrow.replace(hour=start_h, minute=random.randint(0, 30),
                                            second=0, microsecond=0)
                wait = (next_run - now).total_seconds()
                log.info("Proactive: на сегодня всё сделано (%d чатов), сплю до %s",
                         len(chats), next_run)
                await asyncio.sleep(wait)
                continue

            random.shuffle(pending)
            log.info("Proactive: за день надо запостить в %d чатов", len(pending))

            # постим по одному с случайной задержкой между
            for i, uname in enumerate(pending):
                if not _cfg.PROACTIVE_ENABLED:
                    log.info("Proactive disabled — выхожу из цикла")
                    break
                # проверка времени
                hr = datetime.now().hour
                if hr >= end_h:
                    log.info("Proactive: вышли за окно дня, остаток на завтра (%d чатов)",
                             len(pending) - i)
                    break

                await _try_post_to_chat(user_client, uname,
                                        _cfg.PROACTIVE_PER_CHAT_DAY,
                                        _cfg.PROACTIVE_MIN_HOURS_BETWEEN)

                # случайная пауза до следующего поста
                gap = random.uniform(_cfg.PROACTIVE_MIN_GAP_SEC, _cfg.PROACTIVE_MAX_GAP_SEC)
                log.info("Proactive: пауза %.0f мин до следующего чата", gap / 60)
                await asyncio.sleep(gap)

        except Exception as e:
            log.exception("Proactive loop error: %s", e)
            await asyncio.sleep(600)


async def _try_post_to_chat(user_client, uname: str,
                            limit_per_day: int, min_hours_between: int) -> bool:
    """Возвращает True если запостили (или попытались)."""
    from db import proactive_posts_in_chat_24h, last_proactive_post_in_chat, log_proactive_post

    count = await proactive_posts_in_chat_24h(uname)
    if count >= limit_per_day:
        return False

    last = await last_proactive_post_in_chat(uname)
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            hours_passed = (datetime.utcnow() - last_dt).total_seconds() / 3600
            if hours_passed < min_hours_between:
                return False
        except Exception:
            pass

    try:
        entity = await user_client.get_entity(uname)
    except Exception as e:
        log.warning("Can't get entity @%s: %s", uname, e)
        return False

    chat_title = getattr(entity, "title", None) or uname

    # подтянем контекст — последние сообщения чата
    context_msgs: list[str] = []
    try:
        async for msg in user_client.iter_messages(entity, limit=10):
            if msg.message:
                context_msgs.append(msg.message[:200])
    except Exception:
        pass
    context_msgs.reverse()

    text = await _generate_proactive_message(chat_title, context_msgs)
    if not text:
        return False

    # имитация набора: пауза 30-90 секунд
    await asyncio.sleep(random.uniform(30, 90))
    try:
        sent = await user_client.send_message(entity, text)
        await log_proactive_post(uname, sent.id, text)
        log.info("Proactive posted to @%s: %s", uname, text[:80])
        return True
    except Exception as e:
        err_name = type(e).__name__
        if err_name in {"ChatWriteForbiddenError", "UserBannedInChannelError",
                        "ChannelPrivateError", "UserKickedError",
                        "SlowModeWaitError"}:
            from db import remove_dynamic_chat
            await remove_dynamic_chat(uname)
            log.warning("Removed @%s due to %s", uname, err_name)
        else:
            log.warning("Proactive post failed @%s: %s", uname, e)
        return False
