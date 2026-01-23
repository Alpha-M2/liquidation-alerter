"""Position analytics and liquidation prediction.

This module provides simulation and stress testing capabilities for DeFi
positions, including price impact analysis and liquidation risk prediction.
"""

from dataclasses import dataclass
from typing import List

from app.protocols.base import Position


@dataclass
class PriceSimulation:
    price_change_percent: float
    new_health_factor: float
    would_liquidate: bool
    collateral_at_risk_usd: float


@dataclass
class LiquidationPrediction:
    price_drop_to_liquidation_percent: float | None
    estimated_time_to_liquidation: str | None
    risk_level: str


def simulate_price_impact(
    position: Position,
    price_change_percent: float,
) -> PriceSimulation:
    # Simulate collateral value change
    new_collateral = position.total_collateral_usd * (1 + price_change_percent / 100)

    # Calculate new health factor
    if position.total_debt_usd > 0:
        new_hf = (new_collateral * position.liquidation_threshold) / position.total_debt_usd
    else:
        new_hf = float("inf")

    would_liquidate = new_hf <= 1.0
    collateral_at_risk = position.total_collateral_usd if would_liquidate else 0.0

    return PriceSimulation(
        price_change_percent=price_change_percent,
        new_health_factor=new_hf,
        would_liquidate=would_liquidate,
        collateral_at_risk_usd=collateral_at_risk,
    )


def calculate_liquidation_price_drop(position: Position) -> float | None:
    if position.total_debt_usd == 0 or position.health_factor == float("inf"):
        return None

    # Find price drop % that would bring HF to 1.0
    # HF = (collateral * (1 + change) * threshold) / debt = 1.0
    # collateral * (1 + change) * threshold = debt
    # (1 + change) = debt / (collateral * threshold)
    # change = (debt / (collateral * threshold)) - 1
    current_hf_factor = (
        position.total_collateral_usd * position.liquidation_threshold
    ) / position.total_debt_usd

    # The price drop needed is: 1 - (1 / current_hf_factor)
    price_drop = (1 - (1 / current_hf_factor)) * 100
    return max(0, price_drop)


def predict_liquidation(
    position: Position,
) -> LiquidationPrediction:
    price_drop = calculate_liquidation_price_drop(position)

    if price_drop is None:
        return LiquidationPrediction(
            price_drop_to_liquidation_percent=None,
            estimated_time_to_liquidation=None,
            risk_level="None",
        )

    # Determine risk level based on required price drop
    if price_drop <= 5:
        risk_level = "Extreme"
        estimated_time = "Imminent (hours)"
    elif price_drop <= 10:
        risk_level = "Very High"
        estimated_time = "Short-term (days)"
    elif price_drop <= 20:
        risk_level = "High"
        estimated_time = "Medium-term (weeks)"
    elif price_drop <= 30:
        risk_level = "Moderate"
        estimated_time = "Long-term (months)"
    else:
        risk_level = "Low"
        estimated_time = "Very unlikely"

    return LiquidationPrediction(
        price_drop_to_liquidation_percent=price_drop,
        estimated_time_to_liquidation=estimated_time,
        risk_level=risk_level,
    )


def run_stress_test(position: Position) -> List[PriceSimulation]:
    scenarios = [-5, -10, -15, -20, -25, -30, -40, -50]
    return [simulate_price_impact(position, change) for change in scenarios]
