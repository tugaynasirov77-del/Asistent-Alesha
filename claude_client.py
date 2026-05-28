from __future__ import annotations

import json
import logging
import os
import re

from openai import AsyncOpenAI

log = logging.getLogger(__name__)

# OpenRouter — OpenAI-совместимый прокси к Claude, обходит geo-блок Anthropic
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

НЕ матч: общий трёп, мемы, новости, технические вопросы без бизнес-контекста,
вакансии разработчиков (там нанимают, не покупают), реклама чужих услуг.

Верни СТРОГО JSON, без markdown:
- если матч: {"match": true, "reason": "<1-2 предложения почему>", "draft_reply": "<дружелюбный персональный ответ от первого лица, без продажности, ссылается на их конкретную проблему, 2-4 предложения, без эмодзи-спама>"}
- если нет: {"match": false}
"""


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def detect_lead(message_text: str, author: str, chat_title: str) -> dict:
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": LEAD_DETECTOR_PROMPT},
                {
                    "role": "user",
                    "content": f"Чат: {chat_title}\nАвтор: {author}\n\nСообщение:\n{message_text}",
                },
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
