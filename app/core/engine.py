import asyncio
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import Bot

from app.config import get_settings
from app.database import db, User, Wallet, PositionSnapshot
from app.protocols.base import ProtocolAdapter, Position
from app.protocols.aave_v3 import AaveV3Adapter
from app.protocols.aave_v2 import AaveV2Adapter
from app.protocols.compound_v3 import CompoundV3Adapter
from app.protocols.compound_v2 import CompoundV2Adapter
from app.protocols.maker import MakerDAOAdapter
from app.protocols.morpho import MorphoAdapter
from app.core.health import assess_health
from app.core.alerter import GasAwareAlerter
from app.core.cascade import get_cascade_detector, CascadeAlert
from app.services.price import MultiSourcePriceService
from app.bot.messages import format_liquidation_cascade_warning

logger = logging.getLogger(__name__)


class MonitoringEngine:
    def __init__(self, bot: Bot):
        self._bot = bot
        self._alerter = GasAwareAlerter(bot)
        self._price_service = MultiSourcePriceService()
        self._adapters: List[ProtocolAdapter] = [
            AaveV3Adapter(),
            AaveV2Adapter(),
            CompoundV3Adapter(),
            CompoundV2Adapter(),
            MakerDAOAdapter(),
            MorphoAdapter(),
        ]
        self._running = False
        self._settings = get_settings()
        self._gas_price_gwei: float | None = None
        self._eth_price_usd: float | None = None
        self._cascade_detector = get_cascade_detector()
        self._cascade_check_interval = 5  # Check every 5 cycles
        self._cycle_count = 0

    async def start(self):
        self._running = True
        logger.info("Monitoring engine started")

        while self._running:
            try:
                await self._monitor_cycle()
            except Exception as e:
                logger.error(f"Error in monitoring cycle: {e}")

            await asyncio.sleep(self._settings.monitoring_interval_seconds)

    async def stop(self):
        self._running = False
        logger.info("Monitoring engine stopped")

    async def _monitor_cycle(self):
        logger.debug("Starting monitoring cycle")
        self._cycle_count += 1

        # Fetch gas and ETH prices for gas-aware alerting
        try:
            self._gas_price_gwei = await self._price_service.get_gas_price_gwei()
            eth_price = await self._price_service.get_price("ETH")
            self._eth_price_usd = eth_price.price if eth_price else None
        except Exception as e:
            logger.warning(f"Failed to fetch gas/ETH prices: {e}")

        # Check for liquidation cascades periodically
        cascade_alerts = []
        if self._cycle_count % self._cascade_check_interval == 0:
            try:
                cascade_alerts = await self._cascade_detector.check_for_cascades()
            except Exception as e:
                logger.error(f"Error checking for cascades: {e}")

        async with db.async_session() as session:
            result = await session.execute(
                select(User).options(selectinload(User.wallets))
            )
            users = result.scalars().all()

            for user in users:
                # Skip users with paused alerts
                if user.alerts_paused:
                    continue

                # Get user-specific thresholds
                warning_threshold = user.alert_threshold or self._settings.health_factor_threshold
                critical_threshold = user.critical_threshold or self._settings.critical_health_factor_threshold

                for wallet in user.wallets:
                    await self._check_wallet(
                        session,
                        user.chat_id,
                        wallet,
                        warning_threshold,
                        critical_threshold,
                    )

                # Send cascade alerts to users with positions on affected protocols
                if cascade_alerts:
                    await self._send_cascade_alerts(user.chat_id, cascade_alerts)

    async def _check_wallet(
        self,
        session,
        chat_id: int,
        wallet: Wallet,
        warning_threshold: float,
        critical_threshold: float,
    ):
        for adapter in self._adapters:
            try:
                position = await adapter.get_position(wallet.address)
                if position is None:
                    continue

                assessment = assess_health(
                    position,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                )

                # Save snapshot
                snapshot = PositionSnapshot(
                    wallet_id=wallet.id,
                    protocol=adapter.name,
                    health_factor=position.health_factor,
                    total_collateral_usd=position.total_collateral_usd,
                    total_debt_usd=position.total_debt_usd,
                )
                session.add(snapshot)
                await session.commit()

                # Check and send alerts with gas awareness
                await self._alerter.check_and_alert(
                    chat_id,
                    position,
                    assessment,
                    gas_price_gwei=self._gas_price_gwei,
                    eth_price_usd=self._eth_price_usd,
                )

            except Exception as e:
                logger.error(
                    f"Error checking {wallet.address} on {adapter.name}: {e}"
                )

    async def _send_cascade_alerts(
        self,
        chat_id: int,
        cascade_alerts: List[CascadeAlert],
    ):
        """Send cascade alerts to a user."""
        for alert in cascade_alerts:
            try:
                message = format_liquidation_cascade_warning(
                    protocol=alert.protocol,
                    liquidation_count=alert.liquidation_count,
                    total_value_usd=alert.total_value_usd,
                )

                await self._bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                )

                logger.info(
                    f"Cascade alert sent to {chat_id} for {alert.protocol}"
                )

            except Exception as e:
                logger.error(f"Failed to send cascade alert: {e}")

    async def get_positions_for_wallet(self, wallet_address: str) -> List[Position]:
        positions = []
        for adapter in self._adapters:
            try:
                position = await adapter.get_position(wallet_address)
                if position:
                    positions.append(position)
            except Exception as e:
                logger.error(f"Error fetching position from {adapter.name}: {e}")
        return positions

    def get_adapters(self) -> List[ProtocolAdapter]:
        return self._adapters
