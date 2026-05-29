import os
from dotenv import load_dotenv

load_dotenv(override=True)


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Missing env var: {key}")
    return v


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
if not (ANTHROPIC_API_KEY or OPENROUTER_API_KEY):
    raise RuntimeError("Нужен ANTHROPIC_API_KEY или OPENROUTER_API_KEY")

TELEGRAM_API_ID = int(_req("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _req("TELEGRAM_API_HASH")

BOT_TOKEN = _req("BOT_TOKEN")
MY_TELEGRAM_ID = int(_req("MY_TELEGRAM_ID"))

TARGET_GROUPS = [
    g.strip().lstrip("@")
    for g in os.getenv("TARGET_GROUPS", "").split(",")
    if g.strip()
]

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# === Канал для прогрева трафика ===
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "daniil_prim")  # без @
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

DB_PATH = os.getenv("DB_PATH", "alesha.db")
SESSION_NAME = os.getenv("SESSION_NAME", "userbot")

# === Авто-ответы в общих чатах ===
AUTO_REPLY_ENABLED = os.getenv("AUTO_REPLY_ENABLED", "true").lower() == "true"
AUTO_REPLY_MIN_SCORE = int(os.getenv("AUTO_REPLY_MIN_SCORE", "8"))  # отвечаем только горячим
AUTO_REPLY_PER_CHAT_DAY = int(os.getenv("AUTO_REPLY_PER_CHAT_DAY", "5"))  # лимит в чат/сутки
AUTO_REPLY_DELAY_MIN = int(os.getenv("AUTO_REPLY_DELAY_MIN", "30"))  # секунд min
AUTO_REPLY_DELAY_MAX = int(os.getenv("AUTO_REPLY_DELAY_MAX", "90"))  # секунд max
AUTO_REPLY_MAX_AGE_MIN = int(os.getenv("AUTO_REPLY_MAX_AGE_MIN", "10"))  # минут — не отвечать на старое
