import asyncio
import logging
import signal
from contextlib import asynccontextmanager

from app.config import get_settings
from app.database import db
from app.core.engine import MonitoringEngine
from app.bot.handler import create_bot_application, set_engine

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def run_monitoring_engine(engine: MonitoringEngine):
    try:
        await engine.start()
    except asyncio.CancelledError:
        await engine.stop()
        raise


async def main():
    logger.info("Starting DeFi Liquidation Alerter...")

    # Initialize database
    await db.init_db()
    logger.info("Database initialized")

    # Create bot application
    application = create_bot_application()

    # Create and set monitoring engine
    engine = MonitoringEngine(application.bot)
    set_engine(engine)

    # Start monitoring engine as background task
    monitoring_task = asyncio.create_task(run_monitoring_engine(engine))

    # Setup graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Initialize and start the bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot started. Press Ctrl+C to stop.")

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("Shutting down...")
    monitoring_task.cancel()
    try:
        await monitoring_task
    except asyncio.CancelledError:
        pass

    await application.updater.stop()
    await application.stop()
    await application.shutdown()

    logger.info("Shutdown complete")


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
