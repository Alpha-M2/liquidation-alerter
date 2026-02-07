"""
Liquidation cascade detection module.

Monitors on-chain liquidation events to detect potential cascade scenarios
where multiple liquidations in a short time could indicate systemic risk.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List

from web3 import AsyncWeb3

from app.services.rpc import get_web3_provider

logger = logging.getLogger(__name__)


# Liquidation event signatures (keccak256 hash of event signature)
# Note: Cascade detection currently monitors Ethereum mainnet only
# Multi-chain cascade detection would require RPC endpoints for each chain
LIQUIDATION_EVENTS = {
    "Aave V3 (Ethereum)": {
        "address": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "topic": "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286",
        "name": "LiquidationCall",
    },
}


@dataclass
class LiquidationEvent:
    protocol: str
    block_number: int
    tx_hash: str
    liquidator: str
    borrower: str
    debt_covered_usd: float
    collateral_seized_usd: float
    timestamp: datetime


@dataclass
class CascadeAlert:
    protocol: str
    liquidation_count: int
    total_value_usd: float
    time_window_minutes: int
    affected_addresses: List[str]
    severity: str  # "warning", "critical", "severe"
    timestamp: datetime = field(default_factory=datetime.utcnow)


class LiquidationCascadeDetector:
    """
    Detects liquidation cascades by monitoring on-chain events.

    Thresholds:
    - Warning: 5+ liquidations or $1M+ in 1 hour
    - Critical: 10+ liquidations or $5M+ in 1 hour
    - Severe: 20+ liquidations or $10M+ in 1 hour
    """

    # Cascade detection thresholds
    WARNING_COUNT = 5
    WARNING_VALUE_USD = 1_000_000

    CRITICAL_COUNT = 10
    CRITICAL_VALUE_USD = 5_000_000

    SEVERE_COUNT = 20
    SEVERE_VALUE_USD = 10_000_000

    TIME_WINDOW_MINUTES = 60

    def __init__(self):
        self._web3_provider = get_web3_provider()
        self._recent_liquidations: Dict[str, List[LiquidationEvent]] = defaultdict(list)
        self._last_checked_block: Dict[str, int] = {}
        self._alert_history: Dict[str, datetime] = {}
        self._alert_cooldown = timedelta(minutes=30)

    async def check_for_cascades(self) -> List[CascadeAlert]:
        """Check all protocols for liquidation cascades."""
        alerts = []

        for protocol, config in LIQUIDATION_EVENTS.items():
            try:
                cascade_alert = await self._check_protocol(protocol, config)
                if cascade_alert:
                    alerts.append(cascade_alert)
            except Exception as e:
                logger.error(f"Error checking {protocol} for cascades: {e}")

        return alerts

    async def _check_protocol(
        self,
        protocol: str,
        config: dict,
    ) -> CascadeAlert | None:
        """Check a single protocol for liquidation cascade."""
        try:
            web3 = await self._web3_provider.get_web3()

            # Get current block
            current_block = await web3.eth.block_number

            # Determine starting block (look back ~1 hour, ~300 blocks at 12s/block)
            blocks_per_hour = 300
            start_block = self._last_checked_block.get(
                protocol,
                current_block - blocks_per_hour,
            )

            if current_block <= start_block:
                return None

            # Fetch liquidation events
            events = await self._fetch_liquidation_events(
                web3,
                config["address"],
                config["topic"],
                start_block,
                current_block,
            )

            # Parse and store events
            for event in events:
                liquidation = self._parse_liquidation_event(protocol, event)
                if liquidation:
                    self._recent_liquidations[protocol].append(liquidation)

            self._last_checked_block[protocol] = current_block

            # Clean up old events
            self._cleanup_old_events(protocol)

            # Check for cascade
            return self._detect_cascade(protocol)

        except Exception as e:
            logger.error(f"Error checking {protocol}: {e}")
            return None

    async def _fetch_liquidation_events(
        self,
        web3: AsyncWeb3,
        contract_address: str,
        event_topic: str,
        from_block: int,
        to_block: int,
    ) -> List[dict]:
        """Fetch liquidation events from the blockchain."""
        try:
            # Limit block range to avoid RPC errors
            max_block_range = 1000
            if to_block - from_block > max_block_range:
                from_block = to_block - max_block_range

            logs = await web3.eth.get_logs({
                "address": web3.to_checksum_address(contract_address),
                "topics": [event_topic],
                "fromBlock": from_block,
                "toBlock": to_block,
            })

            return logs

        except Exception as e:
            logger.error(f"Error fetching logs: {e}")
            return []

    def _parse_liquidation_event(
        self,
        protocol: str,
        event: dict,
    ) -> LiquidationEvent | None:
        """Parse a raw liquidation event into structured data.

        Aave V3 LiquidationCall event layout:
        - topics[0]: event signature
        - topics[1]: collateralAsset (indexed, address)
        - topics[2]: debtAsset (indexed, address)
        - topics[3]: user/borrower (indexed, address)
        - data: debtToCover (uint256) | liquidatedCollateralAmount (uint256) | liquidator (address) | receiveAToken (bool)
        """
        try:
            tx_hash = event.get("transactionHash", b"").hex()
            block_number = event.get("blockNumber", 0)
            topics = event.get("topics", [])
            data = event.get("data", b"")

            # Decode non-indexed data: debtToCover (uint256) | liquidatedCollateralAmount (uint256) | ...
            # Each uint256 is 32 bytes
            if isinstance(data, (bytes, bytearray)) and len(data) >= 64:
                debt_to_cover_raw = int.from_bytes(data[0:32], "big")
                collateral_seized_raw = int.from_bytes(data[32:64], "big")
                # Assume 8-decimal USD pricing (Chainlink standard); divide by 1e8
                # This gives a rough USD estimate - actual value depends on token decimals
                # For cascade detection, order of magnitude is what matters
                debt_covered_usd = debt_to_cover_raw / 1e8
                collateral_seized_usd = collateral_seized_raw / 1e8
            else:
                debt_covered_usd = 0
                collateral_seized_usd = 0

            borrower = topics[3].hex() if len(topics) > 3 else (topics[2].hex() if len(topics) > 2 else "")
            liquidator = ""
            # Liquidator is in data bytes 64-96 (address padded to 32 bytes)
            if isinstance(data, (bytes, bytearray)) and len(data) >= 96:
                liquidator = "0x" + data[76:96].hex()

            return LiquidationEvent(
                protocol=protocol,
                block_number=block_number,
                tx_hash=tx_hash,
                liquidator=liquidator,
                borrower=borrower,
                debt_covered_usd=debt_covered_usd,
                collateral_seized_usd=collateral_seized_usd,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Error parsing liquidation event: {e}")
            return None

    def _cleanup_old_events(self, protocol: str):
        """Remove events older than the time window."""
        cutoff = datetime.utcnow() - timedelta(minutes=self.TIME_WINDOW_MINUTES)
        self._recent_liquidations[protocol] = [
            e for e in self._recent_liquidations[protocol]
            if e.timestamp >= cutoff
        ]

    def _detect_cascade(self, protocol: str) -> CascadeAlert | None:
        """Detect if current liquidations constitute a cascade."""
        events = self._recent_liquidations[protocol]

        if not events:
            return None

        count = len(events)
        total_value = sum(e.debt_covered_usd for e in events)
        affected = list(set(e.borrower for e in events))

        # Determine severity
        severity = None
        if count >= self.SEVERE_COUNT or total_value >= self.SEVERE_VALUE_USD:
            severity = "severe"
        elif count >= self.CRITICAL_COUNT or total_value >= self.CRITICAL_VALUE_USD:
            severity = "critical"
        elif count >= self.WARNING_COUNT or total_value >= self.WARNING_VALUE_USD:
            severity = "warning"

        if severity is None:
            return None

        # Check cooldown
        last_alert = self._alert_history.get(protocol)
        if last_alert and datetime.utcnow() - last_alert < self._alert_cooldown:
            return None

        self._alert_history[protocol] = datetime.utcnow()

        logger.warning(
            f"Liquidation cascade detected on {protocol}: "
            f"{count} liquidations, ${total_value:,.0f} total value"
        )

        return CascadeAlert(
            protocol=protocol,
            liquidation_count=count,
            total_value_usd=total_value,
            time_window_minutes=self.TIME_WINDOW_MINUTES,
            affected_addresses=affected[:10],  # Limit to 10
            severity=severity,
        )

    def get_recent_liquidations(self, protocol: str) -> List[LiquidationEvent]:
        """Get recent liquidations for a protocol."""
        return self._recent_liquidations.get(protocol, [])

    def get_stats(self) -> dict:
        """Get cascade detection statistics."""
        return {
            protocol: {
                "recent_count": len(events),
                "total_value_usd": sum(e.debt_covered_usd for e in events),
            }
            for protocol, events in self._recent_liquidations.items()
        }


# Singleton instance
_cascade_detector: LiquidationCascadeDetector | None = None


def get_cascade_detector() -> LiquidationCascadeDetector:
    """Get the cascade detector singleton."""
    global _cascade_detector
    if _cascade_detector is None:
        _cascade_detector = LiquidationCascadeDetector()
    return _cascade_detector
