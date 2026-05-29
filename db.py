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
    score INTEGER DEFAULT 5,
    temperature TEXT DEFAULT 'warm',
    product_type TEXT DEFAULT 'custom',
    intent TEXT DEFAULT 'client',   -- client / channel_invite
    status TEXT DEFAULT 'new',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS dynamic_chats (
    username TEXT PRIMARY KEY,
    added_by INTEGER,
    added_at TEXT
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

CREATE TABLE IF NOT EXISTS auto_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    chat_id INTEGER,
    reply_message_id INTEGER,
    text TEXT,
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auto_replies_chat ON auto_replies(chat_id, sent_at);
"""


async def auto_replies_in_chat_24h(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*) FROM auto_replies
               WHERE chat_id = ?
                 AND datetime(sent_at) >= datetime('now', '-24 hours')""",
            (chat_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def log_auto_reply(lead_id: int, chat_id: int, reply_message_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO auto_replies (lead_id, chat_id, reply_message_id, text, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            (lead_id, chat_id, reply_message_id, text, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def save_lead(user_id, username, name, chat_title, chat_id, message,
                    message_id, reason, draft_reply,
                    score: int = 5, temperature: str = "warm",
                    product_type: str = "custom",
                    intent: str = "client") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO leads
               (user_id, username, name, chat_title, chat_id, message, message_id,
                reason, draft_reply, score, temperature, product_type, intent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, name, chat_title, chat_id, message, message_id,
             reason, draft_reply, score, temperature, product_type, intent,
             datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def add_dynamic_chat(username: str, added_by: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO dynamic_chats (username, added_by, added_at) VALUES (?, ?, ?)",
                (username.lower(), added_by, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_dynamic_chat(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM dynamic_chats WHERE username = ?", (username.lower(),)
        )
        await db.commit()
        return cur.rowcount > 0


async def list_dynamic_chats() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT username FROM dynamic_chats ORDER BY username") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def lead_stats(hours: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN temperature='hot' THEN 1 ELSE 0 END) AS hot,
                 SUM(CASE WHEN temperature='warm' THEN 1 ELSE 0 END) AS warm,
                 SUM(CASE WHEN temperature='cold' THEN 1 ELSE 0 END) AS cold,
                 SUM(CASE WHEN status='contacted' THEN 1 ELSE 0 END) AS contacted,
                 SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) AS closed,
                 SUM(CASE WHEN product_type='liva' THEN 1 ELSE 0 END) AS liva,
                 SUM(CASE WHEN product_type='custom' THEN 1 ELSE 0 END) AS custom,
                 SUM(CASE WHEN product_type='both' THEN 1 ELSE 0 END) AS both
               FROM leads
               WHERE datetime(created_at) >= datetime('now', ?)""",
            (f'-{hours} hours',),
        ) as cur:
            row = await cur.fetchone()
    keys = ["total", "hot", "warm", "cold", "contacted", "closed", "liva", "custom", "both"]
    return {k: row[i] or 0 for i, k in enumerate(keys)}


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
