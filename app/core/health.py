from dataclasses import dataclass
from enum import Enum

from app.protocols.base import Position


class HealthStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    LIQUIDATABLE = "liquidatable"


@dataclass
class HealthAssessment:
    status: HealthStatus
    health_factor: float
    normalized_score: float  # 0-100 score
    message: str


def calculate_normalized_score(health_factor: float) -> float:
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
    hf = position.health_factor
    normalized = calculate_normalized_score(hf)

    if hf <= 1.0:
        status = HealthStatus.LIQUIDATABLE
        message = "Position is liquidatable! Immediate action required."
    elif hf <= critical_threshold:
        status = HealthStatus.CRITICAL
        message = f"Critical: Health factor at {hf:.2f}. High liquidation risk!"
    elif hf <= warning_threshold:
        status = HealthStatus.WARNING
        message = f"Warning: Health factor at {hf:.2f}. Consider adding collateral."
    else:
        status = HealthStatus.HEALTHY
        message = f"Healthy: Health factor at {hf:.2f}."

    return HealthAssessment(
        status=status,
        health_factor=hf,
        normalized_score=normalized,
        message=message,
    )


def calculate_safe_withdrawal(
    position: Position,
    target_health_factor: float = 1.5,
) -> float:
    if position.total_debt_usd == 0:
        return position.total_collateral_usd

    # Required collateral to maintain target HF
    # HF = (collateral * liquidation_threshold) / debt
    # collateral = (HF * debt) / liquidation_threshold
    required_collateral = (
        target_health_factor * position.total_debt_usd
    ) / position.liquidation_threshold

    safe_withdrawal = position.total_collateral_usd - required_collateral
    return max(0.0, safe_withdrawal)


def calculate_max_borrow(
    position: Position,
    target_health_factor: float = 1.5,
) -> float:
    # Max debt while maintaining target HF
    # debt = (collateral * liquidation_threshold) / HF
    max_debt = (
        position.total_collateral_usd * position.liquidation_threshold
    ) / target_health_factor

    additional_borrow = max_debt - position.total_debt_usd
    return max(0.0, additional_borrow)
