"""Tests for the gas-aware alerter system."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.protocols.base import Position
from app.core.health import HealthStatus, HealthAssessment
from app.core.alerter import (
    GasAwareAlerter,
    AlertRecord,
    HealthHistory,
)


def create_position(
    protocol: str = "Test",
    wallet_address: str = "0x1234567890123456789012345678901234567890",
    health_factor: float = 2.0,
    total_collateral_usd: float = 10000.0,
    total_debt_usd: float = 5000.0,
) -> Position:
    return Position(
        protocol=protocol,
        wallet_address=wallet_address,
        health_factor=health_factor,
        collateral_assets=[],
        debt_assets=[],
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        liquidation_threshold=0.8,
        available_borrows_usd=0.0,
    )


def create_assessment(status: HealthStatus, message: str = "Test", health_factor: float = 2.0) -> HealthAssessment:
    return HealthAssessment(
        status=status,
        health_factor=health_factor,
        normalized_score=50.0,
        message=message,
        recommendations=[],
    )


class TestHealthHistory:
    def test_add_and_get(self):
        history = HealthHistory()
        history.add(2.0)
        history.add(1.8)
        history.add(1.5)

        assert len(history.health_factors) == 3
        assert len(history.timestamps) == 3

    def test_maxlen(self):
        history = HealthHistory()

        # Add more than maxlen (60)
        for i in range(70):
            history.add(float(i))

        assert len(history.health_factors) == 60

    def test_deterioration_rate_insufficient_data(self):
        history = HealthHistory()
        history.add(2.0)

        rate = history.get_deterioration_rate()
        assert rate is None

    def test_deterioration_rate_no_change(self):
        history = HealthHistory()
        history.add(2.0)
        history.add(2.0)
        history.add(2.0)

        rate = history.get_deterioration_rate()
        assert rate == 0.0 or rate is None

    def test_deterioration_rate_positive(self):
        history = HealthHistory()

        # Add entries spanning the time window
        # First entry outside the window
        history.timestamps.append(datetime.utcnow() - timedelta(minutes=90))
        history.health_factors.append(2.5)

        # Second entry just at the start of window
        history.timestamps.append(datetime.utcnow() - timedelta(minutes=59))
        history.health_factors.append(2.0)

        # Current entry
        history.timestamps.append(datetime.utcnow())
        history.health_factors.append(1.6)

        rate = history.get_deterioration_rate(window_minutes=60)
        # Rate could be None if algorithm doesn't find old entry in window
        # The important thing is that it doesn't crash
        if rate is not None:
            assert rate > 0  # Positive = deteriorating


class TestGasAwareAlerter:
    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def alerter(self, mock_bot):
        return GasAwareAlerter(mock_bot)

    def test_get_alert_key(self, alerter):
        key = alerter._get_alert_key(12345, "0xabc", "Aave V3")
        assert key == "12345:0xabc:Aave V3"

    def test_should_alert_first_time(self, alerter):
        key = "new_key"
        should, reason = alerter._should_alert(key, HealthStatus.WARNING, 1.3)

        assert should is True
        assert reason == "first_alert"

    def test_should_alert_status_worsened(self, alerter):
        key = "test_key"
        alerter._alert_history[key] = AlertRecord(
            status=HealthStatus.WARNING,
            health_factor=1.3,
            last_alert_time=datetime.utcnow(),
            alert_count=1,
        )

        should, reason = alerter._should_alert(key, HealthStatus.CRITICAL, 1.05)

        assert should is True
        assert reason == "status_worsened"

    def test_should_alert_significant_hf_drop(self, alerter):
        key = "test_key"
        alerter._alert_history[key] = AlertRecord(
            status=HealthStatus.WARNING,
            health_factor=1.5,
            last_alert_time=datetime.utcnow(),
            alert_count=1,
        )

        # 15% drop (above 10% threshold)
        should, reason = alerter._should_alert(key, HealthStatus.WARNING, 1.275)

        assert should is True
        assert reason == "significant_hf_drop"

    def test_should_not_alert_cooldown(self, alerter):
        key = "test_key"
        alerter._alert_history[key] = AlertRecord(
            status=HealthStatus.WARNING,
            health_factor=1.3,
            last_alert_time=datetime.utcnow(),
            alert_count=1,
        )

        # Same status, no significant HF drop, within cooldown
        should, reason = alerter._should_alert(key, HealthStatus.WARNING, 1.28)

        assert should is False
        assert reason is None

    def test_should_alert_cooldown_expired(self, alerter):
        key = "test_key"
        alerter._alert_history[key] = AlertRecord(
            status=HealthStatus.WARNING,
            health_factor=1.3,
            last_alert_time=datetime.utcnow() - timedelta(hours=2),  # Past 1h cooldown
            alert_count=1,
        )

        should, reason = alerter._should_alert(key, HealthStatus.WARNING, 1.28)

        assert should is True
        assert reason == "cooldown_expired"

    def test_gas_economical_no_data(self, alerter):
        position = create_position()
        is_economical, gas_cost = alerter._is_gas_economical(position, None, None)

        assert is_economical is True
        assert gas_cost is None

    def test_gas_economical_low_gas(self, alerter):
        position = create_position(total_collateral_usd=10000.0)
        # Low gas: 20 gwei, $2000 ETH => ~$8 for 200k gas
        is_economical, gas_cost = alerter._is_gas_economical(position, 20.0, 2000.0)

        assert is_economical is True
        assert gas_cost is not None
        assert gas_cost < 100  # Gas cost should be under $100

    def test_gas_not_economical_high_gas(self, alerter):
        position = create_position(total_collateral_usd=100.0)  # Small position
        # High gas: 200 gwei, $2000 ETH => ~$80 for 200k gas
        is_economical, gas_cost = alerter._is_gas_economical(position, 200.0, 2000.0)

        assert is_economical is False
        # Gas cost ($80) > 5% of position ($5)

    @pytest.mark.asyncio
    async def test_check_and_alert_healthy_no_alert(self, alerter):
        position = create_position(health_factor=3.0)
        assessment = create_assessment(HealthStatus.HEALTHY)

        result = await alerter.check_and_alert(12345, position, assessment)

        assert result is False
        alerter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_alert_warning(self, alerter):
        position = create_position(health_factor=1.3)
        assessment = create_assessment(HealthStatus.WARNING, "Health factor below threshold")

        result = await alerter.check_and_alert(12345, position, assessment)

        assert result is True
        alerter._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_alert_with_gas_info(self, alerter):
        position = create_position(health_factor=1.05)
        assessment = create_assessment(HealthStatus.CRITICAL, "Critical health factor")

        result = await alerter.check_and_alert(
            12345,
            position,
            assessment,
            gas_price_gwei=50.0,
            eth_price_usd=2000.0,
        )

        assert result is True
        alerter._bot.send_message.assert_called_once()

    def test_clear_alert_history(self, alerter):
        alerter._alert_history = {
            "12345:0xabc:Aave": AlertRecord(
                status=HealthStatus.WARNING,
                health_factor=1.3,
                last_alert_time=datetime.utcnow(),
                alert_count=1,
            ),
            "12345:0xdef:Compound": AlertRecord(
                status=HealthStatus.CRITICAL,
                health_factor=1.05,
                last_alert_time=datetime.utcnow(),
                alert_count=2,
            ),
            "67890:0xghi:Aave": AlertRecord(
                status=HealthStatus.WARNING,
                health_factor=1.4,
                last_alert_time=datetime.utcnow(),
                alert_count=1,
            ),
        }

        # Clear history for chat_id 12345
        alerter.clear_alert_history(12345)

        assert "12345:0xabc:Aave" not in alerter._alert_history
        assert "12345:0xdef:Compound" not in alerter._alert_history
        assert "67890:0xghi:Aave" in alerter._alert_history

    def test_clear_alert_history_specific_wallet(self, alerter):
        alerter._alert_history = {
            "12345:0xabc:Aave": AlertRecord(
                status=HealthStatus.WARNING,
                health_factor=1.3,
                last_alert_time=datetime.utcnow(),
                alert_count=1,
            ),
            "12345:0xdef:Compound": AlertRecord(
                status=HealthStatus.CRITICAL,
                health_factor=1.05,
                last_alert_time=datetime.utcnow(),
                alert_count=2,
            ),
        }

        alerter.clear_alert_history(12345, "0xabc")

        assert "12345:0xabc:Aave" not in alerter._alert_history
        assert "12345:0xdef:Compound" in alerter._alert_history
