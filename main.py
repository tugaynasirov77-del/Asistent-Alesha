import asyncio
import logging

from db import init_db
from monitor import run_monitor
from bot_handlers import init_bot, shutdown_bot
from digest import digest_loop


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


async def _bot_lifecycle():
    """Поднимает бота с бесконечным retry. Если бот всё же упал — пробует заново."""
    while True:
        try:
            await init_bot()
            # держим живым: ждём пока updater не остановится
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.exception("Bot lifecycle crashed: %s — restart in 30s", e)
            await asyncio.sleep(30)


async def main():
    await init_db()
    # Бот и дайджест — параллельно, монитор — основной таск
    bot_task = asyncio.create_task(_bot_lifecycle())
    digest_task = asyncio.create_task(digest_loop())
    try:
        await run_monitor()
    finally:
        bot_task.cancel()
        digest_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
