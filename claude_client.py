from __future__ import annotations

import json
import logging
import os
import re

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

# Через Cloudflare Worker — прокси к api.anthropic.com из РФ
PROXY_URL = os.getenv("PROXY_URL", "https://claude-proxy.mlbbgus924.workers.dev")
PROXY_TOKEN = os.getenv("PROXY_TOKEN", "")

# Дешёвая модель Haiku для детектора (вызывается на каждое сообщение)
# Дорогая Sonnet для регенерации черновика и smart-комментариев (вызывается редко)
MODEL_FAST = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5")
MODEL_SMART = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
MODEL = MODEL_SMART  # обратная совместимость для promo.py

# api_key используется как x-api-key, но настоящий ключ хранится в Cloudflare Worker.
# Авторизация на самом воркере идёт через Authorization: Bearer PROXY_TOKEN
client = AsyncAnthropic(
    api_key="cf-proxy",
    base_url=PROXY_URL,
    default_headers={"Authorization": f"Bearer {PROXY_TOKEN}"},
)


CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "daniil_prim")
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"


LEAD_DETECTOR_PROMPT = f"""Ты — детектор лидов для предпринимателя Тугая (@prim_daniil).

У Тугая есть Telegram-канал: {CHANNEL_URL} — там кейсы и разборы по AI-автоматизации.
Канал — главный актив для прогрева трафика. Везде где можешь — упоминай его естественно.

У Тугая ДВА продукта:

ПРОДУКТ A — «Liva ai» (SaaS, ailiva.ru): AI-администратор за 2 500₽/мес.
Заменяет живого администратора в малом бизнесе (салоны красоты,
барбершопы, фитнес-студии, клиники, СТО, рестораны, юристы, репетиторы).
Отвечает клиентам в Telegram/Авито/WhatsApp/веб-чате 24/7, записывает
в YClients, шлёт напоминания. Лид-магнит: 1000 сообщений бесплатно
без карты, подключение за 15 минут.

ПРОДУКТ B — Кастом под ключ (100k-500k₽+): индивидуальные AI-агенты,
полная автоматизация workflow, Telegram Mini Apps. Для среднего/крупного
бизнеса. Закрытие через личку.

ЗАДАЧА: оценить сообщение из публичного Telegram-чата.

Сигналы матча для A (Liva):
- Владелец/администратор малого офлайн-бизнеса (салон/клиника/студия/СТО/etc.)
- Жалуется на пропущенные заявки, на администратора, на ночные звонки
- Спрашивает про YClients / автозапись / автоответчик
- Ищет недорогое решение записи клиентов / напоминаний

Сигналы матча для B (кастом):
- Ищет разработчика бота / автоматизатора / AI под конкретную задачу
- Описывает сложную интеграцию / уникальный workflow
- Хочет Telegram Mini App, AI-команду, кастомное решение
- Средний+ бизнес: ecommerce, агентство, инфобиз, IT, медиа

НЕ матч:
- общий трёп, мемы, новости, технические вопросы без бизнес-контекста
- вакансии разработчиков (нанимают сами, не покупают)
- КОНКУРЕНТЫ: автор САМ предлагает услуги ("я делаю ботов", "наша
  команда автоматизирует", "пишите в личку"), кейсы своих работ,
  призывы заходить на свой канал/сайт.

Если матч — определи product_type ("liva" / "custom" / "both"):
- "liva" — явно мелкий бизнес из списка ниш, нужно дешёвое массовое решение
- "custom" — средний+ бизнес, нужна индивидуальная разработка
- "both" — может зайти и то и то

Оцени горячесть:
- score 10 + temperature "hot": ИЩЕТ ПРЯМО СЕЙЧАС, готов платить, конкретное ТЗ
- score 7-9 + "hot": явно ищет подрядчика, изучает варианты
- score 4-6 + "warm": есть проблема, но просто узнаёт / сомневается
- score 1-3 + "cold": рассуждает / спрашивает мнение

Тип ответа intent:
- "client" (score 7-10): отвечаем как потенциальному клиенту — зовём на сайт/в личку,
  В КОНЦЕ draft_reply добавляй ТОНКО упоминание канала {CHANNEL_URL}
- "channel_invite" (score 4-6): не дозрел до клиента, но тема интересна → лёгкое
  приглашение в канал {CHANNEL_URL}
- "skip" (score 1-3): match = false

draft_reply правила:
- Для product_type "liva" + intent "client": упомяни ailiva.ru и 1000 сообщений бесплатно
- Для product_type "custom" + intent "client": зови в личку обсудить
- Для intent "channel_invite": ТОЛЬКО приглашение в канал

Верни СТРОГО JSON, без markdown:
{{"match": true, "intent": "client"|"channel_invite", "product_type": "liva"|"custom"|"both", "score": <1-10>, "temperature": "hot"|"warm"|"cold", "reason": "<1-2 предложения>", "draft_reply": "<2-4 предложения>"}}
или {{"match": false}}
"""


REGEN_STYLES = {
    "friendly": "более дружеский, тёплый, как старому знакомому",
    "expert": "более экспертный, через ценность и кейс",
    "short": "максимально короткий, 1-2 предложения, прямой",
}


# ─── Pre-filter (бесплатный, отсекает ~70% мусора до Claude) ─────────

# Ключевые слова которые с высокой вероятностью означают
# что сообщение хотя бы потенциально про автоматизацию / AI / бизнес-задачу
_KEYWORDS = re.compile(
    r"\b("
    # AI / автоматизация
    r"ai|ии|нейросе|нейрос|искусственн|чатбот|chat[\s-]?bot|chatgpt|gpt|claude|"
    r"бот[ауеыо]?|боты|боту|боте|ботом|автоматиз|автоответ|"
    # Разработка / сервисы
    r"mini[\s-]?app|мини[\s-]?апп|telegram[\s-]?app|телеграм[\s-]?апп|"
    r"разработ|программист|фрилансер|спец|подрядч|"
    # CRM / запись
    r"yclients|ыклиентс|amocrm|амо[\s-]?crm|битрикс|crm|срм|"
    r"админ|секрет[ао]р|оператор|менеджер|"
    r"запис[ьа]?ть|клиент|заявк|обработ|"
    # Малый бизнес
    r"салон|барбер|клиник|студи[яю]|кабинет|мастер|"
    # Маркеры запроса
    r"ищ[ауе]|посовет|помогите|нужен|нужн[аоы]|кто[\s-]?делал|кто[\s-]?знает|"
    r"подскаж|порекоменд|выруча[йю]"
    r")\b",
    re.IGNORECASE,
)


def is_potentially_relevant(text: str) -> bool:
    """Бесплатный pre-filter: отсекаем заведомый мусор до Claude."""
    if not text:
        return False
    t = text.strip()
    if len(t) < 20:  # короткие реплики "ок", "+", "спасибо"
        return False
    if len(t) > 4000:  # лонгрид — режем дальше
        t = t[:4000]
    return bool(_KEYWORDS.search(t))


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _resp_text(resp) -> str:
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


async def detect_lead(message_text: str, author: str, chat_title: str,
                      context: list[dict] | None = None) -> dict:
    # Pre-filter: 70% сообщений мусор, отсекаем без вызова Claude
    if not is_potentially_relevant(message_text):
        return {"match": False, "_skipped": "pre_filter"}

    context_block = ""
    if context:
        # из контекста тоже берём только самые свежие 3 (а не 5), чтобы экономить токены
        lines = [f"[{m.get('author', '?')}]: {m.get('text', '')[:200]}" for m in context[-3:]]
        context_block = (
            "\n\nКонтекст чата:\n" + "\n".join(lines) + "\n---\n"
        )
    user_content = (
        f"Чат: {chat_title}\nАвтор: {author}{context_block}\n\n"
        f"ЦЕЛЕВОЕ:\n{message_text[:1500]}"
    )
    try:
        resp = await client.messages.create(
            model=MODEL_FAST,  # Haiku — в 4 раза дешевле Sonnet
            max_tokens=500,
            system=LEAD_DETECTOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        text = _resp_text(resp)
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
    system = (
        LEAD_DETECTOR_PROMPT
        + f"\n\nВАЖНО: предыдущий черновик: «{previous_draft}». "
          f"Сделай НОВЫЙ вариант draft_reply — {style_hint}. match всегда true."
    )
    try:
        resp = await client.messages.create(
            model=MODEL_SMART,  # Sonnet для качества переписки
            max_tokens=600,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Чат: {chat_title}\nАвтор: {author}\n\nСообщение:\n{message_text}",
            }],
        )
        text = _resp_text(resp)
        data = _extract_json(text)
        return (data or {}).get("draft_reply") or previous_draft
    except Exception as e:
        log.exception("regenerate_draft failed: %s", e)
        return previous_draft
