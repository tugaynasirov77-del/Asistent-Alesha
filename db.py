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
    chat_id INTEGER,
    message TEXT,
    message_id INTEGER,
    reason TEXT,
    draft_reply TEXT,
    score INTEGER DEFAULT 5,         -- 1..10 "горячесть"
    temperature TEXT DEFAULT 'warm', -- hot / warm / cold
    status TEXT DEFAULT 'new',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS seen_messages (
    chat_id INTEGER,
    message_id INTEGER,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    added_at TEXT
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def save_lead(user_id, username, name, chat_title, chat_id, message,
                    message_id, reason, draft_reply,
                    score: int = 5, temperature: str = "warm") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO leads
               (user_id, username, name, chat_title, chat_id, message, message_id,
                reason, draft_reply, score, temperature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, name, chat_title, chat_id, message, message_id,
             reason, draft_reply, score, temperature,
             datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_lead(lead_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def update_lead_draft(lead_id: int, new_draft: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE leads SET draft_reply = ? WHERE id = ?",
            (new_draft, lead_id),
        )
        await db.commit()


async def update_lead_status(lead_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE leads SET status = ? WHERE id = ?",
            (status, lead_id),
        )
        await db.commit()


async def add_subscriber(chat_id: int, username: str | None, first_name: str | None) -> bool:
    """True если впервые подписан, False если уже был."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO subscribers (chat_id, username, first_name, added_at) VALUES (?, ?, ?, ?)",
                (chat_id, username, first_name, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def all_subscribers() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM subscribers") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def remove_subscriber(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def history_for_user(user_id: int, limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM leads WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def leads_since(hours: int = 24) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM leads
               WHERE datetime(created_at) >= datetime('now', ?)
               ORDER BY score DESC, id DESC""",
            (f'-{hours} hours',),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def recent_lead_for_user(user_id: int, days: int = 7) -> dict | None:
    """Возвращает последнего лида от user_id за последние N дней, иначе None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM leads
               WHERE user_id = ?
                 AND datetime(created_at) >= datetime('now', ?)
               ORDER BY id DESC LIMIT 1""",
            (user_id, f'-{days} days'),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def mark_seen(chat_id: int, message_id: int) -> bool:
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
