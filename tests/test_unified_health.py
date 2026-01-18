"""Tests for unified cross-protocol health scoring."""

import pytest

from app.protocols.base import Position
from app.core.health import (
    HealthStatus,
    UnifiedHealthScore,
    calculate_unified_health_score,
    calculate_repayment_for_target_hf,
    calculate_deposit_for_target_hf,
)


def create_position(
    protocol: str = "Test",
    health_factor: float = 2.0,
    total_collateral_usd: float = 10000.0,
    total_debt_usd: float = 5000.0,
    liquidation_threshold: float = 0.8,
) -> Position:
    return Position(
        protocol=protocol,
        wallet_address="0x1234567890123456789012345678901234567890",
        health_factor=health_factor,
        collateral_assets=[],
        debt_assets=[],
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        liquidation_threshold=liquidation_threshold,
        available_borrows_usd=0.0,
    )


class TestUnifiedHealthScore:
    def test_empty_positions(self):
        unified = calculate_unified_health_score([])
        assert unified.overall_score == 100.0
        assert unified.overall_status == HealthStatus.HEALTHY
        assert unified.worst_position is None

    def test_single_healthy_position(self):
        positions = [create_position(health_factor=3.0)]
        unified = calculate_unified_health_score(positions)

        assert unified.overall_status == HealthStatus.HEALTHY
        assert unified.overall_score > 80
        assert unified.worst_position is not None
        assert unified.worst_position.health_factor == 3.0

    def test_single_critical_position(self):
        positions = [create_position(health_factor=1.05)]
        unified = calculate_unified_health_score(positions)

        assert unified.overall_status == HealthStatus.CRITICAL
        assert unified.overall_score < 30

    def test_multiple_positions_worst_dominates(self):
        positions = [
            create_position(protocol="Aave V3", health_factor=3.0),
            create_position(protocol="Compound V3", health_factor=1.2),
            create_position(protocol="MakerDAO", health_factor=2.5),
        ]
        unified = calculate_unified_health_score(positions)

        # Worst position should determine overall status
        assert unified.worst_position.protocol == "Compound V3"
        assert unified.overall_status == HealthStatus.WARNING

    def test_weighted_health_factor(self):
        positions = [
            create_position(
                protocol="Large",
                health_factor=2.0,
                total_collateral_usd=90000.0,
                total_debt_usd=45000.0,
            ),
            create_position(
                protocol="Small",
                health_factor=1.2,
                total_collateral_usd=10000.0,
                total_debt_usd=5000.0,
            ),
        ]
        unified = calculate_unified_health_score(positions)

        # Weighted HF should be closer to larger position
        assert unified.weighted_health_factor > 1.5

    def test_protocol_breakdown(self):
        positions = [
            create_position(protocol="Aave V3", health_factor=2.0),
            create_position(protocol="Compound V3", health_factor=1.5),
        ]
        unified = calculate_unified_health_score(positions)

        assert "Aave V3" in unified.protocol_breakdown
        assert "Compound V3" in unified.protocol_breakdown
        assert unified.protocol_breakdown["Aave V3"] == 2.0
        assert unified.protocol_breakdown["Compound V3"] == 1.5

    def test_total_values(self):
        positions = [
            create_position(total_collateral_usd=10000.0, total_debt_usd=5000.0),
            create_position(total_collateral_usd=20000.0, total_debt_usd=8000.0),
        ]
        unified = calculate_unified_health_score(positions)

        assert unified.total_collateral_usd == 30000.0
        assert unified.total_debt_usd == 13000.0


class TestRepaymentCalculation:
    def test_repayment_for_target_hf(self):
        position = create_position(
            health_factor=1.2,
            total_collateral_usd=10000.0,
            total_debt_usd=6666.67,
            liquidation_threshold=0.8,
        )

        # Calculate repayment needed to reach HF 1.5
        repayment = calculate_repayment_for_target_hf(position, target_hf=1.5)

        # At HF 1.5: debt = (10000 * 0.8) / 1.5 = 5333.33
        # Repayment = 6666.67 - 5333.33 = 1333.33
        assert repayment > 1000
        assert repayment < 2000

    def test_no_repayment_needed(self):
        position = create_position(health_factor=2.5)
        repayment = calculate_repayment_for_target_hf(position, target_hf=1.5)
        assert repayment == 0.0

    def test_no_debt_position(self):
        position = create_position(total_debt_usd=0.0)
        repayment = calculate_repayment_for_target_hf(position, target_hf=1.5)
        assert repayment == 0.0


class TestDepositCalculation:
    def test_deposit_for_target_hf(self):
        position = create_position(
            health_factor=1.2,
            total_collateral_usd=10000.0,
            total_debt_usd=6666.67,
            liquidation_threshold=0.8,
        )

        deposit = calculate_deposit_for_target_hf(position, target_hf=1.5)

        # At HF 1.5: collateral = (1.5 * 6666.67) / 0.8 = 12500
        # Deposit = 12500 - 10000 = 2500
        assert deposit > 2000
        assert deposit < 3000

    def test_no_deposit_needed(self):
        position = create_position(health_factor=2.5)
        deposit = calculate_deposit_for_target_hf(position, target_hf=1.5)
        assert deposit == 0.0

    def test_no_debt_position(self):
        position = create_position(total_debt_usd=0.0)
        deposit = calculate_deposit_for_target_hf(position, target_hf=1.5)
        assert deposit == 0.0
