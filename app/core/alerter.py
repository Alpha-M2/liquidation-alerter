import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

from telegram import Bot

from app.protocols.base import Position
from app.core.health import HealthAssessment, HealthStatus
from app.bot.messages import format_alert_message

logger = logging.getLogger(__name__)


@dataclass
class AlertRecord:
    status: HealthStatus
    last_alert_time: datetime
    alert_count: int


class Alerter:
    COOLDOWN_PERIODS = {
        HealthStatus.LIQUIDATABLE: timedelta(minutes=5),
        HealthStatus.CRITICAL: timedelta(minutes=15),
        HealthStatus.WARNING: timedelta(hours=1),
        HealthStatus.HEALTHY: timedelta(hours=24),
    }

    def __init__(self, bot: Bot):
        self._bot = bot
        self._alert_history: Dict[str, AlertRecord] = {}

    def _get_alert_key(self, chat_id: int, wallet_address: str, protocol: str) -> str:
        return f"{chat_id}:{wallet_address}:{protocol}"

    def _should_alert(
        self,
        key: str,
        current_status: HealthStatus,
    ) -> bool:
        if key not in self._alert_history:
            return True

        record = self._alert_history[key]
        cooldown = self.COOLDOWN_PERIODS[current_status]

        # Always alert if status worsened
        status_priority = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.WARNING: 1,
            HealthStatus.CRITICAL: 2,
            HealthStatus.LIQUIDATABLE: 3,
        }
        if status_priority[current_status] > status_priority[record.status]:
            return True

        # Check cooldown period
        time_since_last = datetime.utcnow() - record.last_alert_time
        return time_since_last >= cooldown

    async def check_and_alert(
        self,
        chat_id: int,
        position: Position,
        assessment: HealthAssessment,
    ) -> bool:
        # Don't alert for healthy positions
        if assessment.status == HealthStatus.HEALTHY:
            return False

        key = self._get_alert_key(chat_id, position.wallet_address, position.protocol)

        if not self._should_alert(key, assessment.status):
            return False

        try:
            message = format_alert_message(position, assessment)
            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )

            # Update alert history
            if key in self._alert_history:
                self._alert_history[key].status = assessment.status
                self._alert_history[key].last_alert_time = datetime.utcnow()
                self._alert_history[key].alert_count += 1
            else:
                self._alert_history[key] = AlertRecord(
                    status=assessment.status,
                    last_alert_time=datetime.utcnow(),
                    alert_count=1,
                )

            logger.info(
                f"Alert sent to {chat_id} for {position.wallet_address} on {position.protocol}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def clear_alert_history(self, chat_id: int, wallet_address: str | None = None):
        keys_to_remove = []
        for key in self._alert_history:
            parts = key.split(":")
            if int(parts[0]) == chat_id:
                if wallet_address is None or parts[1] == wallet_address:
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._alert_history[key]
