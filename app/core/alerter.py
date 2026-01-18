import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List
from collections import deque

from telegram import Bot

from app.protocols.base import Position
from app.core.health import HealthAssessment, HealthStatus
from app.bot.messages import format_alert_message, format_gas_warning

logger = logging.getLogger(__name__)


@dataclass
class AlertRecord:
    status: HealthStatus
    health_factor: float
    last_alert_time: datetime
    alert_count: int


@dataclass
class HealthHistory:
    """Track health factor history for deterioration detection."""
    timestamps: deque = field(default_factory=lambda: deque(maxlen=60))
    health_factors: deque = field(default_factory=lambda: deque(maxlen=60))

    def add(self, hf: float):
        self.timestamps.append(datetime.utcnow())
        self.health_factors.append(hf)

    def get_deterioration_rate(self, window_minutes: int = 60) -> float | None:
        """Calculate HF deterioration rate over the window period."""
        if len(self.health_factors) < 2:
            return None

        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        old_hf = None
        old_time = None

        for i, (ts, hf) in enumerate(zip(self.timestamps, self.health_factors)):
            if ts >= cutoff:
                if i > 0:
                    old_hf = self.health_factors[i - 1]
                    old_time = self.timestamps[i - 1]
                break

        if old_hf is None or old_hf == 0:
            return None

        current_hf = self.health_factors[-1]
        deterioration_pct = ((old_hf - current_hf) / old_hf) * 100

        return deterioration_pct


class GasAwareAlerter:
    """
    Alert system with gas awareness and rate deterioration detection.

    Features:
    - Gas-aware recommendations (don't alert for small positions if gas is high)
    - Rapid deterioration detection (>10% HF drop in 1 hour)
    - Smart cooldown periods based on severity
    """

    COOLDOWN_PERIODS = {
        HealthStatus.LIQUIDATABLE: timedelta(minutes=5),
        HealthStatus.CRITICAL: timedelta(minutes=15),
        HealthStatus.WARNING: timedelta(hours=1),
        HealthStatus.HEALTHY: timedelta(hours=24),
    }

    # Minimum position value to alert based on gas costs
    # If gas cost > X% of position, may not be worth alerting
    GAS_COST_THRESHOLD_PERCENT = 5.0

    # Rapid deterioration threshold
    DETERIORATION_THRESHOLD_PERCENT = 10.0

    def __init__(self, bot: Bot):
        self._bot = bot
        self._alert_history: Dict[str, AlertRecord] = {}
        self._health_history: Dict[str, HealthHistory] = {}

    def _get_alert_key(self, chat_id: int, wallet_address: str, protocol: str) -> str:
        return f"{chat_id}:{wallet_address}:{protocol}"

    def _get_history_key(self, wallet_address: str, protocol: str) -> str:
        return f"{wallet_address}:{protocol}"

    def _should_alert(
        self,
        key: str,
        current_status: HealthStatus,
        current_hf: float,
    ) -> tuple[bool, str | None]:
        """
        Determine if we should send an alert.
        Returns (should_alert, reason)
        """
        if key not in self._alert_history:
            return True, "first_alert"

        record = self._alert_history[key]
        cooldown = self.COOLDOWN_PERIODS[current_status]

        # Status priority for comparison
        status_priority = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.WARNING: 1,
            HealthStatus.CRITICAL: 2,
            HealthStatus.LIQUIDATABLE: 3,
        }

        # Always alert if status worsened
        if status_priority[current_status] > status_priority[record.status]:
            return True, "status_worsened"

        # Alert if HF dropped significantly even within same status
        if record.health_factor > 0:
            hf_drop = (record.health_factor - current_hf) / record.health_factor
            if hf_drop > 0.1:  # >10% drop
                return True, "significant_hf_drop"

        # Check cooldown period
        time_since_last = datetime.utcnow() - record.last_alert_time
        if time_since_last >= cooldown:
            return True, "cooldown_expired"

        return False, None

    def _check_rapid_deterioration(
        self,
        wallet_address: str,
        protocol: str,
        current_hf: float,
    ) -> bool:
        """Check if health factor is deteriorating rapidly (>10% in 1 hour)."""
        history_key = self._get_history_key(wallet_address, protocol)

        if history_key not in self._health_history:
            self._health_history[history_key] = HealthHistory()

        history = self._health_history[history_key]
        history.add(current_hf)

        deterioration_rate = history.get_deterioration_rate(window_minutes=60)

        if deterioration_rate and deterioration_rate > self.DETERIORATION_THRESHOLD_PERCENT:
            logger.warning(
                f"Rapid deterioration detected for {wallet_address} on {protocol}: "
                f"{deterioration_rate:.1f}% in 1 hour"
            )
            return True

        return False

    def _is_gas_economical(
        self,
        position: Position,
        gas_price_gwei: float | None,
        eth_price_usd: float | None,
    ) -> tuple[bool, float | None]:
        """
        Check if the position value justifies action given current gas costs.
        Returns (is_economical, estimated_gas_cost_usd)
        """
        if gas_price_gwei is None or eth_price_usd is None:
            return True, None  # Can't determine, assume OK

        # Estimate gas cost for a typical DeFi transaction (~200k gas)
        estimated_gas_units = 200_000
        gas_cost_eth = (gas_price_gwei * estimated_gas_units) / 1e9
        gas_cost_usd = gas_cost_eth * eth_price_usd

        # Check if gas cost is too high relative to position value
        if position.total_collateral_usd > 0:
            gas_to_position_ratio = (gas_cost_usd / position.total_collateral_usd) * 100

            if gas_to_position_ratio > self.GAS_COST_THRESHOLD_PERCENT:
                logger.info(
                    f"Gas cost ${gas_cost_usd:.2f} is {gas_to_position_ratio:.1f}% "
                    f"of position value ${position.total_collateral_usd:.2f}"
                )
                return False, gas_cost_usd

        return True, gas_cost_usd

    async def check_and_alert(
        self,
        chat_id: int,
        position: Position,
        assessment: HealthAssessment,
        gas_price_gwei: float | None = None,
        eth_price_usd: float | None = None,
    ) -> bool:
        """
        Check if alert should be sent and send it.
        Includes gas awareness and deterioration detection.
        """
        # Don't alert for healthy positions (unless rapid deterioration)
        rapid_deterioration = self._check_rapid_deterioration(
            position.wallet_address,
            position.protocol,
            position.health_factor,
        )

        if assessment.status == HealthStatus.HEALTHY and not rapid_deterioration:
            return False

        key = self._get_alert_key(chat_id, position.wallet_address, position.protocol)

        should_alert, reason = self._should_alert(
            key, assessment.status, position.health_factor
        )

        # Force alert on rapid deterioration
        if rapid_deterioration and not should_alert:
            should_alert = True
            reason = "rapid_deterioration"

        if not should_alert:
            return False

        # Check if action is gas-economical
        is_economical, gas_cost_usd = self._is_gas_economical(
            position, gas_price_gwei, eth_price_usd
        )

        try:
            message = format_alert_message(
                position,
                assessment,
                gas_cost_usd=gas_cost_usd,
                rapid_deterioration=rapid_deterioration,
            )

            # Add gas warning if not economical but still critical
            if not is_economical and assessment.status in [
                HealthStatus.CRITICAL,
                HealthStatus.LIQUIDATABLE,
            ]:
                message += "\n\n" + format_gas_warning(gas_cost_usd, position.total_collateral_usd)

            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )

            # Update alert history
            self._alert_history[key] = AlertRecord(
                status=assessment.status,
                health_factor=position.health_factor,
                last_alert_time=datetime.utcnow(),
                alert_count=self._alert_history.get(key, AlertRecord(
                    status=assessment.status,
                    health_factor=position.health_factor,
                    last_alert_time=datetime.utcnow(),
                    alert_count=0,
                )).alert_count + 1,
            )

            logger.info(
                f"Alert sent to {chat_id} for {position.wallet_address} "
                f"on {position.protocol} (reason: {reason})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def clear_alert_history(self, chat_id: int, wallet_address: str | None = None):
        """Clear alert history for a user."""
        keys_to_remove = []
        for key in self._alert_history:
            parts = key.split(":")
            if int(parts[0]) == chat_id:
                if wallet_address is None or parts[1] == wallet_address:
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._alert_history[key]

    def get_deterioration_rate(
        self,
        wallet_address: str,
        protocol: str,
    ) -> float | None:
        """Get current deterioration rate for a position."""
        history_key = self._get_history_key(wallet_address, protocol)
        if history_key in self._health_history:
            return self._health_history[history_key].get_deterioration_rate()
        return None


# Backwards compatibility alias
Alerter = GasAwareAlerter
