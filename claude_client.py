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


LEAD_DETECTOR_PROMPT = f"""Ты — детектор лидов для команды Liva ai (фаундер Даниил Прим, @prim_daniil).

Продукт: «Liva ai» (ailiva.ru) — AI-администратор за 2 500₽/мес.
Канал: {CHANNEL_URL} — кейсы как мелкий бизнес и самозанятые перестали
терять клиентов из-за неотвеченных сообщений.

Стиль ответа: от первого лица МНОЖЕСТВЕННОГО числа («мы делаем», «у нас», «наша команда»).
Это команда, не одиночка.

═══════════ ЦЕЛЕВАЯ АУДИТОРИЯ ═══════════

Малый бизнес и самозанятые в РФ, которые работают «руками» с клиентами:

БЬЮТИ / УСЛУГИ КРАСОТЫ:
- Мастера маникюра, бровисты, лешмейкеры (на себе или в студии 1-3 кресла)
- Парикмахеры, колористы, барберы-частники
- Косметологи, массажисты, мастера депиляции
- Тату-мастера, пирсеры
- Маленькие салоны красоты, студии маникюра, барбершопы (1-5 мастеров)

УСЛУГИ ЭКСПЕРТАМ:
- Репетиторы (язык, школьные предметы, музыка)
- Фитнес-тренеры (персоналки, групповые)
- Психологи, коучи, нутрициологи, диетологи
- Логопеды, дефектологи
- Йога/танцы/растяжка инструкторы

КРЕАТИВ:
- Фотографы, видеографы
- Кондитеры на заказ, домашняя кухня
- Флористы, мастера декора

МИКРО-БИЗНЕС:
- Автосервис на 1-3 поста, шиномонтаж, автомойка
- Ремонт техники, мастер на час
- Маленькие кофейни/пекарни/студии без админа

═══════════ ИХ БОЛИ (которые решает Liva) ═══════════

- «Клиенты пишут в субботу/ночью — отвечаю утром → они уходят к конкурентам»
- «Я и мастер, и менеджер — не успеваю всё»
- «Забываю напомнить — клиент не приходит — теряю деньги»
- «Хочу делегировать запись, но 35-50k за админа — не потяну»
- «Веду запись в блокноте/Заметках/Excel — путаюсь»
- «Авито/Telegram/WhatsApp — каждый отдельно, забываю отвечать»
- «Постоянно одни и те же вопросы: цены, адрес, свободные окна»

═══════════ СИГНАЛЫ МАТЧА ═══════════

ГОРЯЧИЕ (score 8-10):
- Прямо ищет: «посоветуйте автоответчик», «нужен бот для записи», «как автоматизировать»
- Конкретно жалуется: «теряю заявки по ночам», «не успеваю отвечать»
- Спрашивает про инструменты: YClients, Altegio, GreenAPI, чат-бот, CRM
- «Сколько стоит администратор» / «искала админа — дорого»

ТЁПЛЫЕ (score 4-7):
- Описывает рутину которую делает руками: ручная запись, напоминания, ответы
- Жалуется на клиентов которые «не пришли» / «отвалились»
- Обсуждает рост (несколько мастеров, делегирование) но не явный запрос

═══════════ НЕ МАТЧ ═══════════

- Средний/крупный бизнес (>10 сотрудников, >5M оборот) — Liva им не подойдёт
- Корпоративные задачи, сложные интеграции, кастомные AI-агенты
- Конкуренты: «я делаю ботов», «наша команда автоматизирует», «пишите в личку, сделаю»
- Кейсы, прайс, сайты — это реклама услуг, не запрос
- Вакансии разработчиков
- IT/SaaS/диджитал-бизнесы (они сами умеют автоматизировать)
- Общий трёп, мемы, новости

═══════════ ИНСТРУКЦИИ ОТВЕТА ═══════════

intent:
- "client" (score 7-10): черновик-ответ как потенциальному клиенту Liva
- "channel_invite" (score 4-6): приглашение в канал {CHANNEL_URL}
- match=false (score 1-3 или НЕ матч)

draft_reply правила для intent="client":
- Звучит как живой человек, который сам через это прошёл
- Упоминает конкретную боль клиента из его сообщения
- В конце ОБЯЗАТЕЛЬНО: «бесплатно посмотреть как работает: ailiva.ru, 1000 сообщений в подарок» (или формулировка близкая)
- Тонкое упоминание канала {CHANNEL_URL} ("у меня в канале кейсы похожих ребят" / аналогично)
- 2-4 предложения, без воды, без эмодзи-спама, без давления

draft_reply правила для intent="channel_invite":
- Только приглашение в канал {CHANNEL_URL}
- Привязка к их теме: «видел вопрос про X, у меня в канале как раз был разбор как ребята из {{ниши}} решали это»
- 1-3 предложения

product_type всегда = "liva"

Верни СТРОГО JSON, без markdown:
{{"match": true, "intent": "client"|"channel_invite", "product_type": "liva", "score": <1-10>, "temperature": "hot"|"warm"|"cold", "reason": "<1-2 предложения>", "niche": "<ниша автора если понятно: маникюр/барбер/фитнес/etc>", "draft_reply": "<2-4 предложения>"}}
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
    r"("
    # Запись клиентов / админ
    r"запис[ьаи]|клиент|заявк|админ|секрет[ао]р|оператор|менеджер|"
    r"yclients|altegio|алтегио|crm|срм|расписан|напомин|неявк|"
    # AI / автоматизация
    r"\bai\b|\bии\b|нейросе|нейрос|искусственн|чатбот|chat[\s-]?bot|chatgpt|gpt|claude|"
    r"бот[ауеыо]?|боты|автоматиз|автоответ|"
    # Ниши самозанятых/малого бизнеса
    r"маникюр|педикюр|брови|ресниц|шугаринг|депил|массаж|космет|"
    r"парикмах|стрижк|барбер|колорист|"
    r"тренер|фитнес|йог|пилат|растяжк|"
    r"репетитор|преподават|логопед|"
    r"психолог|нутрициолог|диетолог|коуч|"
    r"фотограф|видеограф|кондитер|флорист|"
    r"салон|студи[яю]|кабинет|мастер|самозанят|ип\b|самозан|"
    # Боли
    r"теря[юе]|пропуск|не\sуспева|забыл|забыва|"
    r"админ.{0,15}(нет|дорог|не\sмогу)|"
    # Маркеры запроса
    r"посовет|подскаж|порекоменд|помогите|"
    r"кто[\s-]?(делал|знает|подскажет|пользует)|"
    r"ищ[ауе]|нужен|нужн[аоы]|хочу|хотел"
    r")",
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
