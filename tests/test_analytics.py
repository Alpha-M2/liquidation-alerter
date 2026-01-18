"""Tests for price simulation and liquidation prediction."""

import pytest

from app.protocols.base import Position
from app.core.analytics import (
    simulate_price_impact,
    predict_liquidation,
    run_stress_test,
    PriceSimulation,
    LiquidationPrediction,
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


class TestSimulatePriceImpact:
    def test_no_price_change(self):
        position = create_position(
            health_factor=1.6,  # HF matches (10000 * 0.8) / 5000 = 1.6
            total_collateral_usd=10000.0,
            total_debt_usd=5000.0,
            liquidation_threshold=0.8,
        )
        result = simulate_price_impact(position, 0)

        assert result.price_change_percent == 0
        # HF should be recalculated to same value: (10000 * 0.8) / 5000 = 1.6
        assert abs(result.new_health_factor - 1.6) < 0.01
        assert result.would_liquidate is False

    def test_price_increase(self):
        position = create_position(
            health_factor=1.6,  # HF matches (10000 * 0.8) / 5000 = 1.6
            total_collateral_usd=10000.0,
            total_debt_usd=5000.0,
            liquidation_threshold=0.8,
        )
        result = simulate_price_impact(position, 20)  # 20% price increase

        # Collateral increases to 12000, HF = (12000 * 0.8) / 5000 = 1.92
        assert result.new_health_factor > 1.6
        assert result.would_liquidate is False

    def test_price_decrease_no_liquidation(self):
        position = create_position(
            health_factor=2.0,
            total_collateral_usd=10000.0,
            total_debt_usd=5000.0,
        )
        result = simulate_price_impact(position, -20)  # 20% price decrease

        assert result.new_health_factor < 2.0
        assert result.new_health_factor > 1.0
        assert result.would_liquidate is False

    def test_price_decrease_causes_liquidation(self):
        position = create_position(
            health_factor=1.2,
            total_collateral_usd=10000.0,
            total_debt_usd=6666.67,
            liquidation_threshold=0.8,
        )
        result = simulate_price_impact(position, -30)  # 30% price decrease

        assert result.would_liquidate is True
        assert result.new_health_factor < 1.0

    def test_no_debt_position(self):
        position = create_position(
            total_collateral_usd=10000.0,
            total_debt_usd=0.0,
        )
        result = simulate_price_impact(position, -50)

        assert result.would_liquidate is False
        # HF should remain infinite


class TestPredictLiquidation:
    def test_healthy_position(self):
        # HF 3.0 means collateral can drop significantly before liquidation
        position = create_position(
            health_factor=2.4,  # HF = (10000 * 0.8) / 3333.33 ≈ 2.4
            total_collateral_usd=10000.0,
            total_debt_usd=3333.33,
            liquidation_threshold=0.8,
        )
        prediction = predict_liquidation(position)

        assert prediction.price_drop_to_liquidation_percent is not None
        assert prediction.price_drop_to_liquidation_percent > 30
        assert prediction.risk_level == "Low"

    def test_warning_position(self):
        # HF around 1.4 - needs ~29% price drop
        position = create_position(
            health_factor=1.4,
            total_collateral_usd=10000.0,
            total_debt_usd=5714.29,  # HF = (10000 * 0.8) / 5714.29 ≈ 1.4
            liquidation_threshold=0.8,
        )
        prediction = predict_liquidation(position)

        assert prediction.price_drop_to_liquidation_percent is not None
        # At HF 1.4, price drop needed is about 29%
        assert prediction.risk_level in ["Moderate", "High"]

    def test_critical_position(self):
        # HF around 1.1 - needs ~9% price drop
        position = create_position(
            health_factor=1.1,
            total_collateral_usd=10000.0,
            total_debt_usd=7272.73,  # HF = (10000 * 0.8) / 7272.73 ≈ 1.1
            liquidation_threshold=0.8,
        )
        prediction = predict_liquidation(position)

        assert prediction.price_drop_to_liquidation_percent is not None
        assert prediction.price_drop_to_liquidation_percent < 15
        assert prediction.risk_level in ["Extreme", "Very High"]

    def test_no_debt_position(self):
        position = create_position(total_debt_usd=0.0)
        prediction = predict_liquidation(position)

        assert prediction.price_drop_to_liquidation_percent is None
        assert prediction.risk_level == "None"

    def test_prediction_time_estimate(self):
        position = create_position(
            health_factor=1.5,
            total_collateral_usd=10000.0,
            total_debt_usd=5333.33,  # HF = (10000 * 0.8) / 5333.33 ≈ 1.5
            liquidation_threshold=0.8,
        )
        prediction = predict_liquidation(position)

        assert prediction.estimated_time_to_liquidation is not None
        assert isinstance(prediction.estimated_time_to_liquidation, str)


class TestRunStressTest:
    def test_stress_test_returns_multiple_scenarios(self):
        position = create_position()
        results = run_stress_test(position)

        assert len(results) > 0
        assert all(isinstance(r, PriceSimulation) for r in results)

    def test_stress_test_includes_various_drops(self):
        position = create_position()
        results = run_stress_test(position)

        # Should include different price drop scenarios
        drops = [r.price_change_percent for r in results]
        assert -10 in drops or any(d < 0 for d in drops)
        assert -50 in drops or any(d <= -50 for d in drops)

    def test_stress_test_sorted_by_price_change(self):
        position = create_position()
        results = run_stress_test(position)

        drops = [r.price_change_percent for r in results]
        # Results should be in some order (ascending or descending)
        assert drops == sorted(drops) or drops == sorted(drops, reverse=True)
