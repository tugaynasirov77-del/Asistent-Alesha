from __future__ import annotations

import json
import logging
import os
import re

from openai import AsyncOpenAI

log = logging.getLogger(__name__)

API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("CLAUDE_MODEL", "anthropic/claude-sonnet-4.5")

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)


LEAD_DETECTOR_PROMPT = """Ты — детектор лидов для специалиста по AI-автоматизации.

Услуги Тугая:
- AI-агенты для бизнеса
- Полная автоматизация рутинных процессов
- Кастомные Telegram Mini Apps любого формата

Тебе придёт сообщение из публичного Telegram-чата.
Определи: нужен ли этому человеку один из сервисов Тугая.

Сигналы матча:
- Ищет разработчика бота / автоматизатора / AI
- Жалуется на рутину, ручной труд, "съедает время"
- Хочет автоматизировать процесс / отдел / воронку
- Ищет Telegram-приложение / mini app / web app для бизнеса
- Спрашивает рекомендации по AI-инструментам для бизнеса
- Описывает задачу, которая решается агентом/ботом

НЕ матч (важно!):
- общий трёп, мемы, новости, технические вопросы без бизнес-контекста
- вакансии разработчиков (там нанимают, не покупают)
- реклама чужих услуг
- КОНКУРЕНТЫ: автор САМ предлагает услуги ("я делаю ботов", "наша команда автоматизирует",
  "пишите в личку, сделаю под ключ", прайс, кейсы своих работ, призывы заходить на свой канал/сайт).
  Конкуренты часто пишут в ответ на чей-то запрос или просто рекламируют — это НЕ лид.

Если матч — оцени "горячесть" лида:
- score 9-10 + temperature "hot": открыто ищет подрядчика прямо сейчас, готов платить, конкретное ТЗ
- score 6-8 + temperature "warm": есть проблема, изучает решения, но не "куплю завтра"
- score 1-5 + temperature "cold": просто рассуждает / спрашивает мнение / интересуется

Верни СТРОГО JSON, без markdown:
- если матч: {"match": true, "score": <1-10>, "temperature": "hot"|"warm"|"cold", "reason": "<1-2 предложения почему>", "draft_reply": "<дружелюбный персональный ответ от первого лица, без продажности, ссылается на их конкретную проблему, 2-4 предложения, без эмодзи-спама>"}
- если нет: {"match": false}
"""


REGEN_STYLES = {
    "friendly": "более дружеский, тёплый, как старому знакомому",
    "expert": "более экспертный, через ценность и кейс",
    "short": "максимально короткий, 1-2 предложения, прямой",
}


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def detect_lead(message_text: str, author: str, chat_title: str,
                      context: list[dict] | None = None) -> dict:
    context_block = ""
    if context:
        lines = [
            f"[{m.get('author', '?')}]: {m.get('text', '')}" for m in context
        ]
        context_block = (
            "\n\nКонтекст чата (последние сообщения ДО целевого, для понимания темы):\n"
            + "\n".join(lines)
            + "\n--- конец контекста ---\n"
        )
    user_content = (
        f"Чат: {chat_title}\nАвтор: {author}{context_block}\n\n"
        f"ЦЕЛЕВОЕ СООБЩЕНИЕ (его и оцениваем):\n{message_text}"
    )
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": LEAD_DETECTOR_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json(text)
        if not data:
            log.warning("Bad JSON from detector: %s", text[:200])
            return {"match": False}
        return data
    except Exception as e:
        log.exception("detect_lead failed: %s", e)
        return {"match": False}


async def regenerate_draft(message_text: str, author: str, chat_title: str,
                           previous_draft: str, style: str = "friendly") -> str:
    style_hint = REGEN_STYLES.get(style, REGEN_STYLES["friendly"])
    prompt = (
        f"{LEAD_DETECTOR_PROMPT}\n\n"
        f"ВАЖНО: предыдущий черновик ответа: «{previous_draft}»\n"
        f"Сделай НОВЫЙ вариант draft_reply — {style_hint}. "
        f"Это уже точно лид, поле match всегда true."
    )
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Чат: {chat_title}\nАвтор: {author}\n\nСообщение:\n{message_text}",
                },
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json(text)
        return (data or {}).get("draft_reply") or previous_draft
    except Exception as e:
        log.exception("regenerate_draft failed: %s", e)
        return previous_draft
