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
    # подгружаем сохранённый список каналов для smart-комментариев
    try:
        from promo import reload_competitors_from_db
        await reload_competitors_from_db()
    except Exception as e:
        logging.warning("Could not load competitors: %s", e)
    # Бот и дайджест — параллельно, монитор — основной таск
    bot_task = asyncio.create_task(_bot_lifecycle())
    digest_task = asyncio.create_task(digest_loop())
    proactive_task = None
    try:
        # запускаем проактивные посты после старта монитора
        from proactive import proactive_loop
        from monitor import user_client
        # стартуем после задержки чтобы user_client успел подняться
        async def _delayed_proactive():
            await asyncio.sleep(60)
            await proactive_loop(user_client)
        proactive_task = asyncio.create_task(_delayed_proactive())
        await run_monitor()
    finally:
        bot_task.cancel()
        digest_task.cancel()
        if proactive_task:
            proactive_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
