import pytest

from app.protocols.base import Position
from app.core.health import (
    HealthStatus,
    calculate_normalized_score,
    assess_health,
    calculate_safe_withdrawal,
    calculate_max_borrow,
)


def create_position(
    health_factor: float = 2.0,
    total_collateral_usd: float = 10000.0,
    total_debt_usd: float = 5000.0,
    liquidation_threshold: float = 0.8,
) -> Position:
    return Position(
        protocol="Test",
        wallet_address="0x1234567890123456789012345678901234567890",
        health_factor=health_factor,
        collateral_assets=[],
        debt_assets=[],
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        liquidation_threshold=liquidation_threshold,
        available_borrows_usd=0.0,
    )


class TestCalculateNormalizedScore:
    def test_infinite_health_factor(self):
        assert calculate_normalized_score(float("inf")) == 100.0

    def test_very_high_health_factor(self):
        assert calculate_normalized_score(15.0) == 100.0

    def test_health_factor_at_liquidation(self):
        assert calculate_normalized_score(1.0) == 0.0

    def test_health_factor_below_liquidation(self):
        assert calculate_normalized_score(0.5) == 0.0

    def test_health_factor_1_5(self):
        score = calculate_normalized_score(1.5)
        assert 30 < score < 50

    def test_health_factor_2_0(self):
        score = calculate_normalized_score(2.0)
        assert score == 80.0


class TestAssessHealth:
    def test_healthy_position(self):
        position = create_position(health_factor=3.0)
        assessment = assess_health(position)
        assert assessment.status == HealthStatus.HEALTHY
        assert "Healthy" in assessment.message

    def test_warning_position(self):
        position = create_position(health_factor=1.3)
        assessment = assess_health(position)
        assert assessment.status == HealthStatus.WARNING
        assert "Warning" in assessment.message

    def test_critical_position(self):
        position = create_position(health_factor=1.05)
        assessment = assess_health(position)
        assert assessment.status == HealthStatus.CRITICAL
        assert "Critical" in assessment.message

    def test_liquidatable_position(self):
        position = create_position(health_factor=0.95)
        assessment = assess_health(position)
        assert assessment.status == HealthStatus.LIQUIDATABLE
        assert "liquidatable" in assessment.message.lower()

    def test_custom_thresholds(self):
        position = create_position(health_factor=1.8)
        assessment = assess_health(
            position, warning_threshold=2.0, critical_threshold=1.5
        )
        assert assessment.status == HealthStatus.WARNING


class TestCalculateSafeWithdrawal:
    def test_no_debt(self):
        position = create_position(total_debt_usd=0.0)
        safe = calculate_safe_withdrawal(position)
        assert safe == position.total_collateral_usd

    def test_with_debt(self):
        position = create_position(
            total_collateral_usd=10000.0,
            total_debt_usd=5000.0,
            liquidation_threshold=0.8,
        )
        safe = calculate_safe_withdrawal(position, target_health_factor=1.5)
        # Required collateral = (1.5 * 5000) / 0.8 = 9375
        # Safe withdrawal = 10000 - 9375 = 625
        assert abs(safe - 625.0) < 1.0

    def test_no_safe_withdrawal(self):
        position = create_position(
            total_collateral_usd=5000.0,
            total_debt_usd=5000.0,
            liquidation_threshold=0.8,
        )
        safe = calculate_safe_withdrawal(position, target_health_factor=1.5)
        assert safe == 0.0


class TestCalculateMaxBorrow:
    def test_max_borrow(self):
        position = create_position(
            total_collateral_usd=10000.0,
            total_debt_usd=2000.0,
            liquidation_threshold=0.8,
        )
        max_borrow = calculate_max_borrow(position, target_health_factor=1.5)
        # Max debt = (10000 * 0.8) / 1.5 = 5333.33
        # Additional = 5333.33 - 2000 = 3333.33
        assert abs(max_borrow - 3333.33) < 1.0

    def test_at_limit(self):
        position = create_position(
            total_collateral_usd=10000.0,
            total_debt_usd=5333.33,
            liquidation_threshold=0.8,
        )
        max_borrow = calculate_max_borrow(position, target_health_factor=1.5)
        assert max_borrow < 1.0  # Nearly zero
