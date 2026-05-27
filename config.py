import os
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Missing env var: {key}")
    return v


ANTHROPIC_API_KEY = _req("ANTHROPIC_API_KEY")

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

DB_PATH = os.getenv("DB_PATH", "alesha.db")
SESSION_NAME = os.getenv("SESSION_NAME", "userbot")
