"""Main entry point for the DeFi Liquidation Alerter.

This module initializes and runs all application components:
- Database initialization
- Prometheus metrics server
- Telegram bot for user interaction
- Position monitoring engine

Usage:
    python -m app.main
"""

import asyncio
import logging
import signal
from aiohttp import web

from app.config import get_settings
from app.database import db
from app.core.engine import MonitoringEngine
from app.bot.handler import create_bot_application, set_engine
from app.services.metrics import get_metrics, get_content_type

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


async def metrics_handler(_request: web.Request) -> web.Response:
    """Prometheus metrics endpoint."""
    return web.Response(
        body=get_metrics(),
        content_type=get_content_type(),
    )


async def health_handler(_request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "healthy"})


async def run_metrics_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the metrics HTTP server."""
    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"Metrics server running on http://{host}:{port}/metrics")
    return runner


async def main():
    logger.info("Starting DeFi Liquidation Alerter...")
    settings = get_settings()

    # Initialize database
    await db.init_db()
    logger.info("Database initialized")

    # Start metrics server
    metrics_runner = await run_metrics_server(
        host="0.0.0.0",
        port=settings.metrics_port,
    )

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

    # Cleanup metrics server
    await metrics_runner.cleanup()

    logger.info("Shutdown complete")


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
