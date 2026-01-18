from typing import List

from app.protocols.base import Position
from app.core.health import HealthAssessment, HealthStatus
from app.core.analytics import PriceSimulation, LiquidationPrediction


def get_status_emoji(status: HealthStatus) -> str:
    return {
        HealthStatus.HEALTHY: "🟢",
        HealthStatus.WARNING: "🟡",
        HealthStatus.CRITICAL: "🔴",
        HealthStatus.LIQUIDATABLE: "💀",
    }.get(status, "⚪")


def format_usd(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.2f}K"
    return f"${amount:.2f}"


def format_health_factor(hf: float) -> str:
    if hf == float("inf"):
        return "∞"
    return f"{hf:.2f}"


def format_position_status(position: Position, assessment: HealthAssessment) -> str:
    emoji = get_status_emoji(assessment.status)
    short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"

    return f"""
{emoji} *{position.protocol}* | `{short_addr}`

*Health Factor:* {format_health_factor(position.health_factor)}
*Status:* {assessment.status.value.title()}

*Collateral:* {format_usd(position.total_collateral_usd)}
*Debt:* {format_usd(position.total_debt_usd)}
*Liq. Threshold:* {position.liquidation_threshold:.0%}

_{assessment.message}_
""".strip()


def format_alert_message(position: Position, assessment: HealthAssessment) -> str:
    emoji = get_status_emoji(assessment.status)
    short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"

    if assessment.status == HealthStatus.LIQUIDATABLE:
        header = "⚠️ *LIQUIDATION ALERT* ⚠️"
    elif assessment.status == HealthStatus.CRITICAL:
        header = "🚨 *CRITICAL ALERT* 🚨"
    else:
        header = "⚠️ *WARNING* ⚠️"

    return f"""
{header}

{emoji} *{position.protocol}* | `{short_addr}`

*Health Factor:* {format_health_factor(position.health_factor)}
*Collateral:* {format_usd(position.total_collateral_usd)}
*Debt:* {format_usd(position.total_debt_usd)}

_{assessment.message}_

Consider adding collateral or repaying debt immediately.
""".strip()


def format_simulation_results(simulations: List[PriceSimulation]) -> str:
    lines = ["*Price Impact Simulation*\n"]

    for sim in simulations:
        emoji = "💀" if sim.would_liquidate else ("🔴" if sim.new_health_factor < 1.5 else "🟢")
        status = "LIQUIDATED" if sim.would_liquidate else format_health_factor(sim.new_health_factor)
        lines.append(f"{emoji} {sim.price_change_percent:+.0f}%: HF = {status}")

    return "\n".join(lines)


def format_prediction(prediction: LiquidationPrediction) -> str:
    if prediction.price_drop_to_liquidation_percent is None:
        return "No liquidation risk (no debt position)"

    return f"""
*Liquidation Risk Analysis*

*Price drop to liquidation:* {prediction.price_drop_to_liquidation_percent:.1f}%
*Risk level:* {prediction.risk_level}
*Estimated timeframe:* {prediction.estimated_time_to_liquidation}
""".strip()


def format_welcome_message() -> str:
    return """
👋 *Welcome to DeFi Liquidation Alerter!*

I'll help you monitor your DeFi positions and alert you before liquidation.

*Commands:*
/add `<wallet>` - Add a wallet to monitor
/remove `<wallet>` - Remove a wallet
/status - View all your positions
/simulate `<change%>` - Simulate price impact
/help - Show this help message

*Supported Protocols:*
• Aave V3
• Compound V3

Get started by adding a wallet with /add
""".strip()


def format_help_message() -> str:
    return format_welcome_message()


def format_wallet_added(address: str) -> str:
    short_addr = f"{address[:6]}...{address[-4:]}"
    return f"✅ Wallet `{short_addr}` added successfully!\n\nUse /status to view positions."


def format_wallet_removed(address: str) -> str:
    short_addr = f"{address[:6]}...{address[-4:]}"
    return f"✅ Wallet `{short_addr}` removed successfully."


def format_no_wallets() -> str:
    return "You haven't added any wallets yet.\n\nUse /add `<wallet_address>` to start monitoring."


def format_no_positions(address: str) -> str:
    short_addr = f"{address[:6]}...{address[-4:]}"
    return f"No active positions found for `{short_addr}` on supported protocols."
