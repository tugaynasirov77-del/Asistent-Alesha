import aiosqlite
from datetime import datetime
from config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    name TEXT,
    chat_title TEXT,
    message TEXT,
    reason TEXT,
    draft_reply TEXT,
    status TEXT DEFAULT 'new',  -- new / contacted / closed
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,  -- user / assistant
    content TEXT NOT NULL,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, id);

CREATE TABLE IF NOT EXISTS seen_messages (
    chat_id INTEGER,
    message_id INTEGER,
    PRIMARY KEY (chat_id, message_id)
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def save_lead(user_id, username, name, chat_title, message, reason, draft_reply):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO leads
               (user_id, username, name, chat_title, message, reason, draft_reply, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, name, chat_title, message, reason, draft_reply,
             datetime.utcnow().isoformat()),
        )
        await db.commit()


async def mark_seen(chat_id: int, message_id: int) -> bool:
    """Returns True if newly inserted, False if already seen."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO seen_messages (chat_id, message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def add_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_history(user_id: int, limit: int = 30):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT role, content FROM conversations
               WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]
