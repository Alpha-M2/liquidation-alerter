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
from app.protocols.compound_v3 import CompoundV3Adapter
from app.core.health import assess_health
from app.core.alerter import Alerter

logger = logging.getLogger(__name__)


class MonitoringEngine:
    def __init__(self, bot: Bot):
        self._bot = bot
        self._alerter = Alerter(bot)
        self._adapters: List[ProtocolAdapter] = [
            AaveV3Adapter(),
            CompoundV3Adapter(),
        ]
        self._running = False
        self._settings = get_settings()

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

        async with db.async_session() as session:
            result = await session.execute(
                select(User).options(selectinload(User.wallets))
            )
            users = result.scalars().all()

            for user in users:
                for wallet in user.wallets:
                    await self._check_wallet(session, user.chat_id, wallet)

    async def _check_wallet(self, session, chat_id: int, wallet: Wallet):
        for adapter in self._adapters:
            try:
                position = await adapter.get_position(wallet.address)
                if position is None:
                    continue

                assessment = assess_health(
                    position,
                    warning_threshold=self._settings.health_factor_threshold,
                    critical_threshold=self._settings.critical_health_factor_threshold,
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

                # Check and send alerts
                await self._alerter.check_and_alert(chat_id, position, assessment)

            except Exception as e:
                logger.error(
                    f"Error checking {wallet.address} on {adapter.name}: {e}"
                )

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
