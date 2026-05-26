"""Запустить только Business Bot, без userbot-мониторинга.
Полезно когда userbot ещё не залогинен."""
import asyncio
import logging

from db import init_db
from business_bot import run_bot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


async def main():
    await init_db()
    await run_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
