"""Core monitoring engine for DeFi position tracking.

This module implements the main monitoring loop that periodically checks
positions across all configured protocols and chains. It uses smart polling
to adjust check frequency based on position risk levels and includes
reorg protection to prevent false alerts.
"""

import asyncio
import logging
import time
from typing import List, Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import Bot
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.config import get_settings
from app.database import db, User, Wallet, PositionSnapshot
from app.protocols.base import ProtocolAdapter, Position
from app.protocols.aave_v3 import AaveV3Adapter, AAVE_V3_POOL_ADDRESSES
from app.protocols.compound_v3 import CompoundV3Adapter
from app.core.health import assess_health
from app.core.alerter import GasAwareAlerter
from app.core.cascade import get_cascade_detector, CascadeAlert
from app.services.price import MultiSourcePriceService
from app.services.multicall import BatchPositionFetcher
from app.services.reorg import get_reorg_tracker
from app.bot.messages import format_liquidation_cascade_warning

logger = logging.getLogger(__name__)


class SmartPollingManager:
    """
    Manages adaptive polling intervals based on position health factors.

    High-risk positions are checked more frequently to ensure timely alerts.

    Polling intervals:
    - Critical (HF < 1.3): Every 30 seconds
    - Medium risk (HF 1.3 - 2.0): Every 2 minutes
    - Low risk (HF > 2.0): Every 5 minutes
    - No position / infinite HF: Every 10 minutes
    """

    # Polling intervals in seconds
    CRITICAL_INTERVAL = 30      # HF < 1.3
    MEDIUM_INTERVAL = 120       # HF 1.3 - 2.0
    LOW_INTERVAL = 300          # HF > 2.0
    NO_POSITION_INTERVAL = 600  # No active position

    def __init__(self):
        # Track last check time for each wallet:protocol combination
        self._last_check: Dict[str, float] = {}
        # Track last known health factor for each wallet:protocol
        self._health_factors: Dict[str, float] = {}

    def _get_key(self, wallet_address: str, protocol: str) -> str:
        """Generate a unique key for wallet:protocol combination."""
        return f"{wallet_address.lower()}:{protocol}"

    def get_polling_interval(self, health_factor: float) -> int:
        """
        Get the appropriate polling interval based on health factor.

        Args:
            health_factor: Current health factor (float("inf") for no debt)

        Returns:
            Polling interval in seconds
        """
        if health_factor == float("inf"):
            return self.NO_POSITION_INTERVAL
        elif health_factor < 1.3:
            return self.CRITICAL_INTERVAL
        elif health_factor < 2.0:
            return self.MEDIUM_INTERVAL
        else:
            return self.LOW_INTERVAL

    def should_check(self, wallet_address: str, protocol: str) -> bool:
        """
        Determine if a wallet:protocol should be checked based on its polling interval.

        Args:
            wallet_address: Wallet address
            protocol: Protocol name

        Returns:
            True if the position should be checked this cycle
        """
        key = self._get_key(wallet_address, protocol)
        now = time.time()

        last_check = self._last_check.get(key, 0)
        last_hf = self._health_factors.get(key, float("inf"))

        interval = self.get_polling_interval(last_hf)
        time_since_check = now - last_check

        return time_since_check >= interval

    def record_check(self, wallet_address: str, protocol: str, health_factor: float):
        """
        Record that a position was checked and update its health factor.

        Args:
            wallet_address: Wallet address
            protocol: Protocol name
            health_factor: Current health factor
        """
        key = self._get_key(wallet_address, protocol)
        self._last_check[key] = time.time()
        self._health_factors[key] = health_factor

    def get_wallets_to_check(
        self,
        wallet_addresses: List[str],
        protocols: List[str],
    ) -> Dict[str, List[str]]:
        """
        Filter wallets that should be checked for each protocol.

        Args:
            wallet_addresses: List of all wallet addresses
            protocols: List of protocol names

        Returns:
            Dict mapping protocol -> list of wallet addresses to check
        """
        result: Dict[str, List[str]] = {}

        for protocol in protocols:
            wallets_to_check = [
                addr for addr in wallet_addresses
                if self.should_check(addr, protocol)
            ]
            if wallets_to_check:
                result[protocol] = wallets_to_check

        return result

    def get_stats(self) -> Dict[str, any]:
        """Get polling statistics."""
        critical_count = 0
        medium_count = 0
        low_count = 0

        for key, hf in self._health_factors.items():
            if hf == float("inf"):
                continue
            elif hf < 1.3:
                critical_count += 1
            elif hf < 2.0:
                medium_count += 1
            else:
                low_count += 1

        return {
            "tracked_positions": len(self._health_factors),
            "critical_risk": critical_count,
            "medium_risk": medium_count,
            "low_risk": low_count,
        }


class MonitoringEngine:
    def __init__(self, bot: Bot):
        self._bot = bot
        self._alerter = GasAwareAlerter(bot)
        self._price_service = MultiSourcePriceService()
        self._adapters: List[ProtocolAdapter] = [
            # Aave V3 adapters for each chain
            AaveV3Adapter(chain="ethereum"),
            AaveV3Adapter(chain="arbitrum"),
            AaveV3Adapter(chain="base"),
            AaveV3Adapter(chain="optimism"),
            # Compound V3 adapters for each chain
            CompoundV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="arbitrum"),
            CompoundV3Adapter(chain="base"),
            CompoundV3Adapter(chain="optimism"),
        ]
        self._running = False
        self._settings = get_settings()
        self._gas_price_gwei: float | None = None
        self._eth_price_usd: float | None = None
        self._cascade_detector = get_cascade_detector()
        self._cascade_check_interval = 5  # Check every 5 cycles
        self._cycle_count = 0

        # Initialize Web3 instances and batch fetchers for each chain
        self._web3_instances: Dict[str, AsyncWeb3] = {}
        self._batch_fetchers: Dict[str, BatchPositionFetcher] = {}
        self._init_batch_fetchers()

        # Smart polling manager for adaptive intervals based on risk
        self._polling_manager = SmartPollingManager()

        # Reorg-safe state tracker for preventing false alerts
        self._reorg_tracker = get_reorg_tracker()

    def _init_batch_fetchers(self):
        """Initialize Web3 instances and batch fetchers for each chain."""
        chains = ["ethereum", "arbitrum", "base", "optimism"]

        for chain in chains:
            rpc_url = self._settings.get_rpc_url(chain)
            web3 = AsyncWeb3(
                AsyncHTTPProvider(rpc_url),
                modules={"eth": (AsyncEth,)},
            )
            self._web3_instances[chain] = web3
            self._batch_fetchers[chain] = BatchPositionFetcher(web3)

    async def _update_block_numbers(self):
        """Fetch current block numbers for all chains (used for reorg handling)."""
        chains = ["ethereum", "arbitrum", "base", "optimism"]

        for chain in chains:
            try:
                web3 = self._web3_instances.get(chain)
                if web3:
                    block_number = await web3.eth.block_number
                    self._reorg_tracker.update_block_number(chain, block_number)
            except Exception as e:
                logger.debug(f"Failed to fetch block number for {chain}: {e}")

    async def _batch_fetch_aave_positions(
        self,
        chain: str,
        wallet_addresses: List[str],
    ) -> Dict[str, Position | None]:
        """
        Batch fetch Aave V3 positions for multiple wallets using Multicall.

        Returns a dict mapping wallet_address -> Position (or None if no position).
        """
        if not wallet_addresses:
            return {}

        pool_address = AAVE_V3_POOL_ADDRESSES.get(chain)
        if not pool_address:
            return {}

        fetcher = self._batch_fetchers.get(chain)
        if not fetcher:
            return {}

        try:
            results = await fetcher.fetch_aave_positions(pool_address, wallet_addresses)

            positions = {}
            for wallet, data in results:
                if data and (data["total_collateral_base"] > 0 or data["total_debt_base"] > 0):
                    positions[wallet] = Position(
                        protocol=f"Aave V3 ({chain.capitalize()})",
                        wallet_address=wallet,
                        health_factor=data["health_factor"],
                        collateral_assets=[],
                        debt_assets=[],
                        total_collateral_usd=data["total_collateral_base"],
                        total_debt_usd=data["total_debt_base"],
                        liquidation_threshold=data["liquidation_threshold"],
                        available_borrows_usd=data["available_borrows_base"],
                    )
                else:
                    positions[wallet] = None

            logger.debug(f"Batch fetched {len(positions)} Aave positions on {chain}")
            return positions

        except Exception as e:
            logger.error(f"Batch fetch failed for Aave on {chain}: {e}")
            return {}

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

        # Fetch current block numbers for reorg handling
        await self._update_block_numbers()

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

            # Collect all unique wallet addresses for batch fetching
            all_wallets: Dict[str, Tuple[User, Wallet]] = {}
            for user in users:
                if user.alerts_paused:
                    continue
                for wallet in user.wallets:
                    all_wallets[wallet.address.lower()] = (user, wallet)

            wallet_addresses = list(all_wallets.keys())

            # Use smart polling to determine which wallets need checking
            chains = ["ethereum", "arbitrum", "base", "optimism"]
            aave_protocols = [f"Aave V3 ({c.capitalize()})" for c in chains]
            compound_protocols = [f"Compound V3 ({c.capitalize()})" for c in chains]

            # Get wallets that need Aave checks based on smart polling intervals
            wallets_to_check = self._polling_manager.get_wallets_to_check(
                wallet_addresses, aave_protocols + compound_protocols
            )

            # Batch fetch Aave positions for all chains using Multicall
            aave_positions: Dict[str, Dict[str, Position | None]] = {}

            for chain in chains:
                protocol_name = f"Aave V3 ({chain.capitalize()})"
                wallets_for_chain = wallets_to_check.get(protocol_name, [])

                if not wallets_for_chain:
                    aave_positions[chain] = {}
                    continue

                try:
                    aave_positions[chain] = await self._batch_fetch_aave_positions(
                        chain, wallets_for_chain
                    )
                    logger.debug(
                        f"Smart polling: checked {len(wallets_for_chain)} wallets on {protocol_name}"
                    )
                except Exception as e:
                    logger.error(f"Failed to batch fetch Aave positions on {chain}: {e}")
                    aave_positions[chain] = {}

            # Process each user's wallets with the batch-fetched data
            for user in users:
                if user.alerts_paused:
                    continue

                warning_threshold = user.alert_threshold or self._settings.health_factor_threshold
                critical_threshold = user.critical_threshold or self._settings.critical_health_factor_threshold

                for wallet in user.wallets:
                    # Process batch-fetched Aave positions
                    for chain in chains:
                        chain_positions = aave_positions.get(chain, {})
                        position = chain_positions.get(wallet.address.lower())

                        if position:
                            await self._process_position(
                                session,
                                user.chat_id,
                                wallet,
                                position,
                                f"Aave V3 ({chain.capitalize()})",
                                warning_threshold,
                                critical_threshold,
                            )

                    # Compound V3 positions still fetched individually
                    # (Compound has more complex data fetching that's harder to batch)
                    await self._check_compound_positions(
                        session,
                        user.chat_id,
                        wallet,
                        warning_threshold,
                        critical_threshold,
                    )

                if cascade_alerts:
                    await self._send_cascade_alerts(user.chat_id, cascade_alerts)

    def _get_chain_from_protocol(self, protocol_name: str) -> str:
        """Extract chain name from protocol name (e.g., 'Aave V3 (Ethereum)' -> 'ethereum')."""
        if "(" in protocol_name and ")" in protocol_name:
            chain = protocol_name.split("(")[1].split(")")[0].lower()
            return chain
        return "ethereum"

    async def _process_position(
        self,
        session,
        chat_id: int,
        wallet: Wallet,
        position: Position,
        protocol_name: str,
        warning_threshold: float,
        critical_threshold: float,
    ):
        """Process a single position: save snapshot and check for alerts with reorg safety."""
        try:
            assessment = assess_health(
                position,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
            )

            # Save snapshot
            snapshot = PositionSnapshot(
                wallet_id=wallet.id,
                protocol=protocol_name,
                health_factor=position.health_factor,
                total_collateral_usd=position.total_collateral_usd,
                total_debt_usd=position.total_debt_usd,
            )
            session.add(snapshot)
            await session.commit()

            # Record check in smart polling manager
            self._polling_manager.record_check(
                wallet.address, protocol_name, position.health_factor
            )

            # Record state for reorg handling
            chain = self._get_chain_from_protocol(protocol_name)
            block_number = self._reorg_tracker.get_block_number(chain)

            is_new_confirmed, confirmed_state = self._reorg_tracker.record_state(
                wallet_address=wallet.address,
                protocol=protocol_name,
                health_factor=position.health_factor,
                total_collateral_usd=position.total_collateral_usd,
                total_debt_usd=position.total_debt_usd,
                block_number=block_number,
            )

            # Only alert if the state is confirmed (prevents false alerts during reorgs)
            if confirmed_state is None:
                logger.debug(
                    f"Position {wallet.address} on {protocol_name} pending confirmation "
                    f"(HF: {position.health_factor:.2f})"
                )
                return

            # Check and send alerts (alerter has its own cooldown logic)
            await self._alerter.check_and_alert(
                chat_id,
                position,
                assessment,
                gas_price_gwei=self._gas_price_gwei,
                eth_price_usd=self._eth_price_usd,
            )

        except Exception as e:
            logger.error(f"Error processing position for {wallet.address} on {protocol_name}: {e}")

    async def _check_compound_positions(
        self,
        session,
        chat_id: int,
        wallet: Wallet,
        warning_threshold: float,
        critical_threshold: float,
    ):
        """Check Compound V3 positions (not batched due to complexity)."""
        compound_adapters = [a for a in self._adapters if isinstance(a, CompoundV3Adapter)]

        for adapter in compound_adapters:
            # Use smart polling to skip wallets that don't need checking yet
            if not self._polling_manager.should_check(wallet.address, adapter.name):
                continue

            try:
                position = await adapter.get_position(wallet.address)
                if position:
                    await self._process_position(
                        session,
                        chat_id,
                        wallet,
                        position,
                        adapter.name,
                        warning_threshold,
                        critical_threshold,
                    )
                else:
                    # No position, but still record the check
                    self._polling_manager.record_check(
                        wallet.address, adapter.name, float("inf")
                    )
            except Exception as e:
                logger.error(f"Error checking {wallet.address} on {adapter.name}: {e}")

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
        """Get basic positions for a wallet across all protocols."""
        positions = []
        for adapter in self._adapters:
            try:
                position = await adapter.get_position(wallet_address)
                if position:
                    positions.append(position)
            except Exception as e:
                logger.error(f"Error fetching position from {adapter.name}: {e}")
        return positions

    async def get_detailed_positions_for_wallet(self, wallet_address: str) -> List[Position]:
        """Get detailed positions with per-asset breakdown for a wallet.

        Returns positions with collateral_assets and debt_assets populated.
        Falls back to basic position if detailed fetching fails.
        """
        positions = []
        for adapter in self._adapters:
            try:
                position = await adapter.get_detailed_position(wallet_address)
                if position:
                    positions.append(position)
            except Exception as e:
                logger.error(f"Error fetching detailed position from {adapter.name}: {e}")
                # Try fallback to basic position
                try:
                    position = await adapter.get_position(wallet_address)
                    if position:
                        positions.append(position)
                except Exception:
                    pass
        return positions

    def get_adapters(self) -> List[ProtocolAdapter]:
        return self._adapters

    def get_polling_stats(self) -> Dict[str, any]:
        """Get smart polling statistics."""
        return self._polling_manager.get_stats()

    def get_reorg_stats(self) -> Dict[str, any]:
        """Get reorg tracker statistics."""
        return self._reorg_tracker.get_stats()
