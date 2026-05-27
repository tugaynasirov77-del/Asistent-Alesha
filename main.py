import asyncio
import logging

from db import init_db
from monitor import run_monitor
from business_bot import run_bot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


async def main():
    await init_db()
    await asyncio.gather(
        run_monitor(),
        run_bot(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
