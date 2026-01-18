from dataclasses import dataclass, field
from enum import Enum
from typing import List

from app.protocols.base import Position


class HealthStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    LIQUIDATABLE = "liquidatable"


@dataclass
class ActionRecommendation:
    action_type: str  # "deposit", "repay", "swap"
    description: str
    amount_usd: float
    token_symbol: str | None = None
    priority: int = 1  # 1 = highest


@dataclass
class HealthAssessment:
    status: HealthStatus
    health_factor: float
    normalized_score: float  # 0-100 score
    message: str
    recommendations: List[ActionRecommendation] = field(default_factory=list)


@dataclass
class UnifiedHealthScore:
    """Cross-protocol unified risk score."""
    overall_score: float  # 0-100 (100 = safest)
    overall_status: HealthStatus
    total_collateral_usd: float
    total_debt_usd: float
    weighted_health_factor: float
    worst_position: Position | None
    positions: List[Position]
    protocol_breakdown: dict  # protocol -> health_factor


def calculate_normalized_score(health_factor: float) -> float:
    """Convert health factor to 0-100 score."""
    if health_factor == float("inf") or health_factor > 10:
        return 100.0
    if health_factor <= 1.0:
        return 0.0
    # Map HF 1.0-2.0 to score 0-80, HF 2.0-10.0 to score 80-100
    if health_factor <= 2.0:
        return (health_factor - 1.0) * 80.0
    return 80.0 + ((health_factor - 2.0) / 8.0) * 20.0


def assess_health(
    position: Position,
    warning_threshold: float = 1.5,
    critical_threshold: float = 1.1,
) -> HealthAssessment:
    """Assess health of a single position with recommendations."""
    hf = position.health_factor
    normalized = calculate_normalized_score(hf)
    recommendations = []

    if hf <= 1.0:
        status = HealthStatus.LIQUIDATABLE
        message = "Position is liquidatable! Immediate action required."
        # Calculate exact repayment needed
        repay_amount = calculate_repayment_for_target_hf(position, target_hf=1.5)
        deposit_amount = calculate_deposit_for_target_hf(position, target_hf=1.5)
        recommendations = [
            ActionRecommendation(
                action_type="repay",
                description=f"Repay ${repay_amount:,.2f} debt to reach 1.5 HF",
                amount_usd=repay_amount,
                priority=1,
            ),
            ActionRecommendation(
                action_type="deposit",
                description=f"Or deposit ${deposit_amount:,.2f} collateral",
                amount_usd=deposit_amount,
                priority=2,
            ),
        ]
    elif hf <= critical_threshold:
        status = HealthStatus.CRITICAL
        message = f"Critical: Health factor at {hf:.2f}. High liquidation risk!"
        repay_amount = calculate_repayment_for_target_hf(position, target_hf=1.5)
        deposit_amount = calculate_deposit_for_target_hf(position, target_hf=1.5)
        recommendations = [
            ActionRecommendation(
                action_type="repay",
                description=f"Repay ${repay_amount:,.2f} to reach 1.5 HF",
                amount_usd=repay_amount,
                priority=1,
            ),
            ActionRecommendation(
                action_type="deposit",
                description=f"Or deposit ${deposit_amount:,.2f} collateral",
                amount_usd=deposit_amount,
                priority=2,
            ),
        ]
    elif hf <= warning_threshold:
        status = HealthStatus.WARNING
        message = f"Warning: Health factor at {hf:.2f}. Consider adding collateral."
        deposit_amount = calculate_deposit_for_target_hf(position, target_hf=2.0)
        if deposit_amount > 0:
            recommendations = [
                ActionRecommendation(
                    action_type="deposit",
                    description=f"Deposit ${deposit_amount:,.2f} to reach 2.0 HF",
                    amount_usd=deposit_amount,
                    priority=1,
                ),
            ]
    else:
        status = HealthStatus.HEALTHY
        message = f"Healthy: Health factor at {hf:.2f}."

    return HealthAssessment(
        status=status,
        health_factor=hf,
        normalized_score=normalized,
        message=message,
        recommendations=recommendations,
    )


def calculate_unified_health_score(positions: List[Position]) -> UnifiedHealthScore:
    """
    Calculate a unified cross-protocol health score.

    The unified score considers:
    - Weighted average health factor by debt amount
    - Worst position (minimum HF) for risk assessment
    - Total exposure across all protocols
    """
    if not positions:
        return UnifiedHealthScore(
            overall_score=100.0,
            overall_status=HealthStatus.HEALTHY,
            total_collateral_usd=0.0,
            total_debt_usd=0.0,
            weighted_health_factor=float("inf"),
            worst_position=None,
            positions=[],
            protocol_breakdown={},
        )

    total_collateral = sum(p.total_collateral_usd for p in positions)
    total_debt = sum(p.total_debt_usd for p in positions)

    # Calculate weighted health factor by debt
    weighted_hf_sum = 0.0
    weight_sum = 0.0
    min_hf = float("inf")
    worst_position = None
    protocol_breakdown = {}

    for position in positions:
        if position.total_debt_usd > 0:
            hf = position.health_factor
            weight = position.total_debt_usd

            # Handle infinite HF
            if hf != float("inf"):
                weighted_hf_sum += hf * weight
                weight_sum += weight

            if hf < min_hf:
                min_hf = hf
                worst_position = position

        protocol_breakdown[position.protocol] = position.health_factor

    # Calculate weighted average HF
    if weight_sum > 0:
        weighted_hf = weighted_hf_sum / weight_sum
    else:
        weighted_hf = float("inf")

    # Overall score is based on the WORST position (most conservative)
    # This ensures users are alerted about their riskiest position
    overall_score = calculate_normalized_score(min_hf)

    # Determine overall status based on worst position
    if min_hf <= 1.0:
        overall_status = HealthStatus.LIQUIDATABLE
    elif min_hf <= 1.1:
        overall_status = HealthStatus.CRITICAL
    elif min_hf <= 1.5:
        overall_status = HealthStatus.WARNING
    else:
        overall_status = HealthStatus.HEALTHY

    return UnifiedHealthScore(
        overall_score=overall_score,
        overall_status=overall_status,
        total_collateral_usd=total_collateral,
        total_debt_usd=total_debt,
        weighted_health_factor=weighted_hf,
        worst_position=worst_position,
        positions=positions,
        protocol_breakdown=protocol_breakdown,
    )


def calculate_repayment_for_target_hf(
    position: Position,
    target_hf: float = 1.5,
) -> float:
    """Calculate how much debt to repay to reach target health factor."""
    if position.total_debt_usd == 0 or position.health_factor >= target_hf:
        return 0.0

    # HF = (collateral * threshold) / debt
    # target_hf = (collateral * threshold) / new_debt
    # new_debt = (collateral * threshold) / target_hf
    max_debt = (
        position.total_collateral_usd * position.liquidation_threshold
    ) / target_hf

    repayment = position.total_debt_usd - max_debt
    return max(0.0, repayment)


def calculate_deposit_for_target_hf(
    position: Position,
    target_hf: float = 1.5,
) -> float:
    """Calculate how much collateral to deposit to reach target health factor."""
    if position.total_debt_usd == 0 or position.health_factor >= target_hf:
        return 0.0

    # HF = (collateral * threshold) / debt
    # target_hf = (new_collateral * threshold) / debt
    # new_collateral = (target_hf * debt) / threshold
    required_collateral = (
        target_hf * position.total_debt_usd
    ) / position.liquidation_threshold

    deposit = required_collateral - position.total_collateral_usd
    return max(0.0, deposit)


def calculate_safe_withdrawal(
    position: Position,
    target_health_factor: float = 1.5,
) -> float:
    """Calculate maximum safe collateral withdrawal."""
    if position.total_debt_usd == 0:
        return position.total_collateral_usd

    required_collateral = (
        target_health_factor * position.total_debt_usd
    ) / position.liquidation_threshold

    safe_withdrawal = position.total_collateral_usd - required_collateral
    return max(0.0, safe_withdrawal)


def calculate_max_borrow(
    position: Position,
    target_health_factor: float = 1.5,
) -> float:
    """Calculate maximum additional borrow while maintaining target HF."""
    max_debt = (
        position.total_collateral_usd * position.liquidation_threshold
    ) / target_health_factor

    additional_borrow = max_debt - position.total_debt_usd
    return max(0.0, additional_borrow)


def calculate_liquidation_price(
    position: Position,
    collateral_symbol: str = "ETH",
    current_price: float | None = None,
) -> float | None:
    """
    Calculate the price at which a position would be liquidated.

    Returns the price of the collateral asset at which HF = 1.0
    """
    if position.total_debt_usd == 0 or position.total_collateral_usd == 0:
        return None

    if current_price is None:
        return None

    # At liquidation: HF = 1.0
    # 1.0 = (collateral_value * threshold) / debt
    # collateral_value = debt / threshold
    # collateral_amount * liquidation_price = debt / threshold
    # liquidation_price = debt / (threshold * collateral_amount)

    # Assuming collateral is priced at current_price
    collateral_amount = position.total_collateral_usd / current_price

    liquidation_price = position.total_debt_usd / (
        position.liquidation_threshold * collateral_amount
    )

    return liquidation_price


def calculate_price_drop_to_liquidation(
    position: Position,
) -> float | None:
    """
    Calculate percentage price drop needed for liquidation.

    Returns the percentage drop (e.g., 25.0 means 25% drop triggers liquidation)
    """
    if position.health_factor == float("inf") or position.total_debt_usd == 0:
        return None

    # Current: HF = (collateral * threshold) / debt
    # At liquidation: 1.0 = (collateral * (1-drop) * threshold) / debt
    # (1-drop) = debt / (collateral * threshold)
    # drop = 1 - debt / (collateral * threshold)

    current_hf_factor = (
        position.total_collateral_usd * position.liquidation_threshold
    ) / position.total_debt_usd

    price_drop = (1 - (1 / current_hf_factor)) * 100
    return max(0.0, price_drop)
