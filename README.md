# Алёша — Telegram лид-мониторинг + продающий бот

Система из двух частей:

1. **Group Monitor (Pyrogram userbot)** — слушает указанные Telegram-группы с твоего аккаунта, прогоняет каждое новое сообщение через Claude и, если человеку нужен AI-агент / автоматизация / Telegram Mini App, присылает тебе уведомление с готовым черновиком ответа.
2. **Business Bot (python-telegram-bot)** — отдельный бот, который ведёт переписку с входящими клиентами как «Алёша, ассистент Тугая», и пингует тебя, когда клиент готов закрываться.

## Стек

- Python 3.11+
- [Pyrogram](https://docs.pyrogram.org/) + TgCrypto — userbot
- [python-telegram-bot](https://python-telegram-bot.org/) — бот для входящих
- [anthropic](https://pypi.org/project/anthropic/) — Claude API
- aiosqlite — лиды и история диалогов
- python-dotenv — секреты

## Структура

```
.
├── config.py           # читает .env
├── db.py               # SQLite: leads, conversations, seen_messages
├── claude_client.py    # промпты + вызовы Claude
├── monitor.py          # Pyrogram userbot + бот-уведомитель
├── business_bot.py     # PTB бот для входящих
├── main.py             # запускает обе части
├── requirements.txt
├── .env.example
└── README.md
```

## Установка

```bash
git clone https://github.com/tugaynasirov77-del/Asistent-Alesha.git
cd Asistent-Alesha

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

## Настройка `.env`

1. **ANTHROPIC_API_KEY** — ключ из https://console.anthropic.com/
2. **TELEGRAM_API_ID / TELEGRAM_API_HASH** — получи на https://my.telegram.org → API development tools.
3. **BOT_TOKEN** — создай бота у [@BotFather](https://t.me/BotFather) (`/newbot`).
4. **MY_TELEGRAM_ID** — твой числовой Telegram ID. Узнать: напиши [@userinfobot](https://t.me/userinfobot).
5. **TARGET_GROUPS** — username-ы публичных групп через запятую, без `@`:
   ```
   TARGET_GROUPS=startup_ru,founders_chat,no_code_ru
   ```
   Твой аккаунт должен быть **участником** этих групп.
6. **CLAUDE_MODEL** — модель Claude (по умолчанию `claude-sonnet-4-6`).

> Если хочешь, чтобы бот работал именно как «Business bot» в Telegram Premium —
> в настройках Telegram → Business → Chatbots укажи username твоего бота.
> Тогда он автоматически будет отвечать клиентам, которые пишут на твой личный аккаунт.
> Без этого он работает как обычный @-бот с тем же поведением.

## Первый запуск

```bash
python main.py
```

При первом запуске Pyrogram попросит:
- номер телефона твоего аккаунта;
- код из Telegram;
- 2FA пароль (если включён).

После этого создастся файл `userbot.session` — больше логиниться не придётся.

## Что происходит дальше

- Каждое новое сообщение в `TARGET_GROUPS` отправляется в Claude с промптом-детектором лидов.
- Перед обработкой — рандомная пауза 3-7 секунд (антиспам/имитация человека).
- Если матч — лид сохраняется в SQLite (`alesha.db`, таблица `leads`) и тебе приходит уведомление от бота.
- Когда лид пишет твоему боту — Алёша ведёт диалог, держа историю (таблица `conversations`).
- Когда Claude в ответе возвращает `[READY_TO_CLOSE] резюме` — ты получаешь алерт.

## Полезные SQL-запросы

```bash
sqlite3 alesha.db "SELECT id, username, status, substr(message,1,80) FROM leads ORDER BY id DESC LIMIT 20;"
sqlite3 alesha.db "UPDATE leads SET status='contacted' WHERE id=42;"
```

## Безопасность

- `.env`, `*.session`, `*.db` в `.gitignore` — не коммитятся.
- Все секреты только через `.env`.
- API-ошибки логируются, но не валят процесс.

## Траблшутинг

| Проблема | Решение |
|---|---|
| `Missing env var: X` | заполни переменную в `.env` |
| Userbot не видит группы | проверь, что аккаунт состоит в этих группах и username верный |
| Бот не отвечает в личке | напиши боту `/start`, проверь `BOT_TOKEN` |
| `peer id invalid` для `MY_TELEGRAM_ID` | напиши боту любое сообщение хотя бы раз, чтобы он "узнал" тебя |
| Pyrogram session lock | удали `userbot.session-journal`, не запускай два инстанса одновременно |

## Лицензия

MIT.
