import asyncio

from app.core.database import close_db
from app.services.pipeline import logger, run_trigger


async def main():
    await run_trigger()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Trigger stopped by user.")
    finally:
        close_db()
