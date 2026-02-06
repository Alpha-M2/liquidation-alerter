"""Message formatting utilities for Telegram bot responses.

This module provides functions to format position data, alerts, and other
information into Telegram-friendly Markdown messages with proper escaping
and visual formatting using emojis.
"""

from typing import List

from app.protocols.base import Position, CollateralAsset, DebtAsset
from app.core.health import (
    HealthAssessment,
    HealthStatus,
    UnifiedHealthScore,
)
from app.core.analytics import PriceSimulation, LiquidationPrediction

# Protocol deep links
PROTOCOL_URLS = {
    "Aave V3 (Ethereum)": "https://app.aave.com/",
    "Aave V3 (Arbitrum)": "https://app.aave.com/?marketName=proto_arbitrum_v3",
    "Aave V3 (Base)": "https://app.aave.com/?marketName=proto_base_v3",
    "Aave V3 (Optimism)": "https://app.aave.com/?marketName=proto_optimism_v3",
    "Compound V3 (Ethereum)": "https://app.compound.finance/",
    "Compound V3 (Arbitrum)": "https://app.compound.finance/?market=usdc-arbitrum",
    "Compound V3 (Base)": "https://app.compound.finance/?market=usdc-base",
    "Compound V3 (Optimism)": "https://app.compound.finance/?market=usdc-optimism",
}


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


def format_usd_short(amount: float) -> str:
    """Format USD amount in short form for tables (e.g., $264K, $1.2M)."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


def format_balance_short(balance: float) -> str:
    """Format token balance for table display."""
    if balance >= 1_000_000:
        return f"{balance / 1_000_000:.2f}M"
    if balance >= 1_000:
        return f"{balance / 1_000:.2f}K"
    if balance >= 1:
        return f"{balance:.2f}"
    if balance >= 0.01:
        return f"{balance:.4f}"
    return f"{balance:.6f}"


def format_collateral_table(assets: List[CollateralAsset]) -> str:
    """Format collateral assets as a monospace table block."""
    if not assets:
        return "```\nNo collateral assets\n```"

    lines = ["Asset     Balance      Value    APY"]
    for asset in assets:
        symbol = asset.symbol[:7].ljust(7)
        bal = format_balance_short(asset.balance).rjust(9)
        val = format_usd_short(asset.balance_usd).rjust(8)
        apy = f"+{asset.supply_apy * 100:.1f}%" if asset.supply_apy else "   -"
        apy = apy.rjust(6)
        lines.append(f"{symbol}  {bal}  {val}  {apy}")

    return "```\n" + "\n".join(lines) + "\n```"


def format_debt_table(assets: List[DebtAsset]) -> str:
    """Format debt assets as a monospace table block."""
    if not assets:
        return "```\nNo debt\n```"

    lines = ["Asset       Debt      Value    APY"]
    for asset in assets:
        symbol = asset.symbol[:7].ljust(7)
        bal = format_balance_short(asset.balance).rjust(9)
        val = format_usd_short(asset.balance_usd).rjust(8)
        apy = f"-{asset.borrow_apy * 100:.1f}%" if asset.borrow_apy else "   -"
        apy = apy.rjust(6)
        lines.append(f"{symbol}  {bal}  {val}  {apy}")

    return "```\n" + "\n".join(lines) + "\n```"


def format_health_factor(hf: float) -> str:
    if hf == float("inf"):
        return "∞"
    return f"{hf:.2f}"


def get_protocol_url(protocol: str) -> str:
    return PROTOCOL_URLS.get(protocol, "https://defillama.com/")


def format_position_status(
    position: Position,
    assessment: HealthAssessment,
    include_recommendations: bool = True,
) -> str:
    """Format basic position status for display."""
    emoji = get_status_emoji(assessment.status)
    short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"
    protocol_url = get_protocol_url(position.protocol)

    msg = f"""
{emoji} *{position.protocol}* | `{short_addr}`

*Health Factor:* {format_health_factor(position.health_factor)}
*Status:* {assessment.status.value.title()}

*Collateral:* {format_usd(position.total_collateral_usd)}
*Debt:* {format_usd(position.total_debt_usd)}
*Liq. Threshold:* {position.liquidation_threshold:.0%}
""".strip()

    # Add liquidation risk info if position has debt
    if assessment.price_drop_to_liquidation_percent is not None:
        msg += f"\n*Price Drop to Liq:* {assessment.price_drop_to_liquidation_percent:.1f}%"

    msg += f"\n\n_{assessment.message}_"

    # Add recommendations if available
    if include_recommendations and assessment.recommendations:
        msg += "\n\n*Suggested Actions:*"
        for rec in assessment.recommendations[:2]:  # Show top 2
            msg += f"\n• {rec.description}"

    # Add deep link
    msg += f"\n\n[Open {position.protocol}]({protocol_url})"

    return msg


def format_detailed_position_status(
    position: Position,
    assessment: HealthAssessment,
    include_recommendations: bool = True,
) -> str:
    """Format detailed position status with per-asset breakdown.

    Shows individual collateral and debt assets with their balances,
    APYs, risk parameters, and liquidation risk metrics in a clean
    table-like format.
    """
    emoji = get_status_emoji(assessment.status)
    short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"
    protocol_url = get_protocol_url(position.protocol)

    # Header
    msg = f"{emoji} *{position.protocol}* | `{short_addr}`\n\n"

    # Summary section in monospace
    hf_display = format_health_factor(position.health_factor)
    net_apy_str = ""
    if position.net_apy is not None:
        net_apy_str = f"+{position.net_apy * 100:.1f}%" if position.net_apy >= 0 else f"{position.net_apy * 100:.1f}%"
    else:
        net_apy_str = "N/A"

    msg += f"```\nHealth Factor: {hf_display} {emoji}\n"
    msg += f"Net APY:       {net_apy_str}\n```\n\n"

    # Supplied section
    msg += "📈 *Supplied*\n"
    if position.collateral_assets:
        msg += format_collateral_table(position.collateral_assets)
    else:
        msg += f"```\nTotal: {format_usd_short(position.total_collateral_usd)}\n```"
    msg += "\n\n"

    # Borrowed section
    msg += "💸 *Borrowed*\n"
    if position.debt_assets:
        msg += format_debt_table(position.debt_assets)
    else:
        if position.total_debt_usd > 0:
            msg += f"```\nTotal: {format_usd_short(position.total_debt_usd)}\n```"
        else:
            msg += "```\nNo debt\n```"
    msg += "\n"

    # Risk metrics (compact)
    if assessment.price_drop_to_liquidation_percent is not None:
        msg += f"\n*Price Drop to Liq:* {assessment.price_drop_to_liquidation_percent:.1f}%"

    # Assessment message
    msg += f"\n_{assessment.message}_"

    # Add recommendations if available
    if include_recommendations and assessment.recommendations:
        msg += "\n\n*Suggested Actions:*"
        for rec in assessment.recommendations[:2]:
            msg += f"\n• {rec.description}"

    # Add deep link
    msg += f"\n\n[Open {position.protocol}]({protocol_url})"

    return msg


def format_alert_message(
    position: Position,
    assessment: HealthAssessment,
    gas_cost_usd: float | None = None,
    rapid_deterioration: bool = False,
) -> str:
    emoji = get_status_emoji(assessment.status)
    short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"
    protocol_url = get_protocol_url(position.protocol)

    if assessment.status == HealthStatus.LIQUIDATABLE:
        header = "⚠️ *LIQUIDATION ALERT* ⚠️"
    elif assessment.status == HealthStatus.CRITICAL:
        header = "🚨 *CRITICAL ALERT* 🚨"
    elif rapid_deterioration:
        header = "📉 *RAPID DETERIORATION* 📉"
    else:
        header = "⚠️ *WARNING* ⚠️"

    msg = f"""
{header}

{emoji} *{position.protocol}* | `{short_addr}`

*Health Factor:* {format_health_factor(position.health_factor)}
*Collateral:* {format_usd(position.total_collateral_usd)}
*Debt:* {format_usd(position.total_debt_usd)}

_{assessment.message}_
""".strip()

    # Add recommendations with exact amounts
    if assessment.recommendations:
        msg += "\n\n*Take Action:*"
        for rec in assessment.recommendations:
            msg += f"\n• {rec.description}"

    # Add gas context
    if gas_cost_usd is not None:
        msg += f"\n\n*Est. Gas Cost:* {format_usd(gas_cost_usd)}"

    # Add deep link
    msg += f"\n\n[⚡ Open {position.protocol}]({protocol_url})"

    return msg


def format_gas_warning(gas_cost_usd: float | None, position_value: float) -> str:
    if gas_cost_usd is None:
        return ""

    ratio = (gas_cost_usd / position_value) * 100 if position_value > 0 else 0

    return f"""
⛽ *Gas Warning*
Current gas cost ({format_usd(gas_cost_usd)}) is {ratio:.1f}% of your position value.
Consider waiting for lower gas prices if not urgent.
""".strip()


def format_unified_health_score(unified: UnifiedHealthScore) -> str:
    emoji = get_status_emoji(unified.overall_status)

    msg = f"""
{emoji} *Portfolio Health Overview*

*Overall Risk Score:* {unified.overall_score:.0f}/100
*Total Collateral:* {format_usd(unified.total_collateral_usd)}
*Total Debt:* {format_usd(unified.total_debt_usd)}
*Weighted HF:* {format_health_factor(unified.weighted_health_factor)}

*Protocol Breakdown:*
""".strip()

    for protocol, hf in unified.protocol_breakdown.items():
        proto_emoji = "🟢" if hf > 1.5 else ("🟡" if hf > 1.1 else "🔴")
        msg += f"\n{proto_emoji} {protocol}: HF = {format_health_factor(hf)}"

    if unified.worst_position:
        msg += f"\n\n⚠️ *Riskiest Position:* {unified.worst_position.protocol}"

    return msg


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
/status - View all your positions with detailed breakdown
/simulate `<change%>` - Simulate price impact
/set\\_threshold `<value>` - Set alert threshold (default: 1.5)
/protocols - View supported protocols
/pause - Pause alerts
/resume - Resume alerts
/export - Export position history (CSV)
/help - Show this help message

*Supported Protocols:*
• Aave V3 (Ethereum, Arbitrum, Base, Optimism)
• Compound V3 (Ethereum, Arbitrum, Base, Optimism)

Get started by adding a wallet with /add
""".strip()


def format_help_message() -> str:
    return format_welcome_message()


def format_protocols_list() -> str:
    return """
*Supported Protocols & Chains:*

🔵 *Aave V3*
  • Ethereum - [app.aave.com](https://app.aave.com/)
  • Arbitrum - [app.aave.com](https://app.aave.com/?marketName=proto_arbitrum_v3)
  • Base - [app.aave.com](https://app.aave.com/?marketName=proto_base_v3)
  • Optimism - [app.aave.com](https://app.aave.com/?marketName=proto_optimism_v3)

🟢 *Compound V3*
  • Ethereum - [app.compound.finance](https://app.compound.finance/)
  • Arbitrum - [app.compound.finance](https://app.compound.finance/?market=usdc-arbitrum)
  • Base - [app.compound.finance](https://app.compound.finance/?market=usdc-base)
  • Optimism - [app.compound.finance](https://app.compound.finance/?market=usdc-optimism)
""".strip()


def format_threshold_set(threshold: float) -> str:
    return f"✅ Alert threshold set to *{threshold:.2f}*\n\nYou'll receive warnings when health factor drops below this value."


def format_alerts_paused() -> str:
    return "⏸️ Alerts *paused*.\n\nUse /resume to start receiving alerts again."


def format_alerts_resumed() -> str:
    return "▶️ Alerts *resumed*.\n\nYou'll now receive alerts for positions at risk."


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


def format_liquidation_cascade_warning(
    protocol: str,
    liquidation_count: int,
    total_value_usd: float,
) -> str:
    return f"""
🌊 *Liquidation Cascade Alert*

*{liquidation_count}* large liquidations detected on *{protocol}* in the last hour.

Total value liquidated: {format_usd(total_value_usd)}

This may indicate systemic risk. Consider reviewing your positions on this protocol.
""".strip()


def format_historical_summary(
    avg_hf: float,
    min_hf: float,
    max_hf: float,
    closest_call_hf: float,
    closest_call_date: str,
) -> str:
    return f"""
*Historical Analysis*

*Average Health Factor:* {format_health_factor(avg_hf)}
*Lowest HF:* {format_health_factor(min_hf)}
*Highest HF:* {format_health_factor(max_hf)}

*Closest Call:* HF = {format_health_factor(closest_call_hf)} on {closest_call_date}
""".strip()
