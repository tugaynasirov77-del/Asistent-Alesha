import json
import logging
import re
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

log = logging.getLogger(__name__)

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


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


SALES_SYSTEM_PROMPT = """Ты — Алёша, дружелюбный ассистент Тугая.

Тугай продаёт:
- AI-агентов для бизнеса (поддержка, продажи, ресёрч, контент)
- Полную автоматизацию рабочих процессов
- Кастомные Telegram Mini Apps под любую задачу

Твоя цель: понять проблему клиента, показать как Тугай её решит,
снять возражения, подвести к звонку или сделке.

Стиль:
- Человечно, тепло, по делу
- Без корпоративщины ("в нашей компании", "мы предлагаем решения")
- Короткие сообщения, как в живом чате
- Задавай вопросы, чтобы понять контекст
- Не дави, не продавай в лоб

Когда клиент явно готов обсуждать цену, сроки или подписать —
заверши ответ строкой:
[READY_TO_CLOSE] <короткое резюме что ему нужно>
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
    """Returns {match: bool, reason?, draft_reply?}."""
    try:
        resp = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            system=LEAD_DETECTOR_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Чат: {chat_title}\nАвтор: {author}\n\nСообщение:\n{message_text}",
            }],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        data = _extract_json(text)
        if not data:
            log.warning("Bad JSON from detector: %s", text[:200])
            return {"match": False}
        return data
    except Exception as e:
        log.exception("detect_lead failed: %s", e)
        return {"match": False}


async def sales_reply(history: list[dict], user_message: str) -> str:
    messages = history + [{"role": "user", "content": user_message}]
    resp = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        system=SALES_SYSTEM_PROMPT,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
