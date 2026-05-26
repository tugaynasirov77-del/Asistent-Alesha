import asyncio
import logging
import threading

from db import init_db
from monitor import run_monitor
from business_bot import run_bot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


def _bot_thread():
    """Бот живёт в отдельном asyncio loop в своём потоке —
    иначе конфликтует с pyrogram, который любит владеть основным loop."""
    asyncio.run(run_bot())


async def main():
    await init_db()
    threading.Thread(target=_bot_thread, daemon=True, name="business-bot").start()
    await run_monitor()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
