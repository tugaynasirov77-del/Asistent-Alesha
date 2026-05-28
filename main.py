import asyncio
import logging

from db import init_db
from monitor import run_monitor
from bot_handlers import init_bot, shutdown_bot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


async def main():
    await init_db()
    bot_app = await init_bot()
    try:
        await run_monitor()
    finally:
        await shutdown_bot(bot_app)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
