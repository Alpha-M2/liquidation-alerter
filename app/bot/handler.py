"""Telegram bot command handlers for the DeFi Liquidation Alerter.

This module implements all Telegram bot commands including wallet management,
position status, simulations, and user preferences. Commands are registered
with the python-telegram-bot framework.
"""

import csv
import io
import logging
import re
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from sqlalchemy import select, delete, func
from web3 import Web3

from app.config import get_settings
from app.database import db, User, Wallet, PositionSnapshot
from app.core.engine import MonitoringEngine
from app.core.health import assess_health, calculate_unified_health_score
from app.core.analytics import simulate_price_impact, predict_liquidation, run_stress_test
from app.bot.messages import (
    format_welcome_message,
    format_help_message,
    format_wallet_added,
    format_wallet_removed,
    format_no_wallets,
    format_no_positions,
    format_position_status,
    format_detailed_position_status,
    format_simulation_results,
    format_prediction,
    format_protocols_list,
    format_threshold_set,
    format_alerts_paused,
    format_alerts_resumed,
    format_unified_health_score,
    format_historical_summary,
)

logger = logging.getLogger(__name__)

# Global engine reference - set during app initialization
_engine: MonitoringEngine | None = None


def set_engine(engine: MonitoringEngine):
    global _engine
    _engine = engine


def is_valid_eth_address(address: str) -> bool:
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))


async def get_or_create_user(chat_id: int) -> User:
    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_or_create_user(update.effective_chat.id)
    await update.message.reply_text(
        format_welcome_message(),
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        format_help_message(),
        parse_mode="Markdown",
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please provide a wallet address.\n\nUsage: /add `<wallet_address>`",
            parse_mode="Markdown",
        )
        return

    address = context.args[0].strip()

    if not is_valid_eth_address(address):
        await update.message.reply_text(
            "Invalid Ethereum address. Please provide a valid 0x address.",
        )
        return

    checksum_address = Web3.to_checksum_address(address)
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        result = await session.execute(
            select(Wallet).where(
                Wallet.user_id == user.id,
                Wallet.address == checksum_address,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            await update.message.reply_text(
                "This wallet is already being monitored.",
            )
            return

        wallet = Wallet(user_id=user.id, address=checksum_address)
        session.add(wallet)
        await session.commit()

    await update.message.reply_text(
        format_wallet_added(checksum_address),
        parse_mode="Markdown",
    )


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please provide a wallet address.\n\nUsage: /remove `<wallet_address>`",
            parse_mode="Markdown",
        )
        return

    address = context.args[0].strip()

    if not is_valid_eth_address(address):
        await update.message.reply_text(
            "Invalid Ethereum address.",
        )
        return

    checksum_address = Web3.to_checksum_address(address)
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        result = await session.execute(
            delete(Wallet).where(
                Wallet.user_id == user.id,
                Wallet.address == checksum_address,
            )
        )

        if result.rowcount == 0:
            await update.message.reply_text("Wallet not found in your monitored list.")
            return

        await session.commit()

    await update.message.reply_text(
        format_wallet_removed(checksum_address),
        parse_mode="Markdown",
    )


async def _get_user_wallets_and_thresholds(chat_id: int) -> tuple[list[Wallet], float, float] | None:
    """Fetch user's wallets and alert thresholds from database.

    Returns:
        Tuple of (wallets, warning_threshold, critical_threshold) or None if no user/wallets
    """
    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            return None

        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user.id)
        )
        wallets = result.scalars().all()

        if not wallets:
            return None

        warning_threshold = user.alert_threshold or 1.5
        critical_threshold = user.critical_threshold or 1.1

        return list(wallets), warning_threshold, critical_threshold


async def _build_position_response(
    wallets: list[Wallet],
    warning_threshold: float,
    critical_threshold: float,
    detailed: bool = False,
) -> str:
    """Build formatted position response for all wallets.

    Args:
        wallets: List of user's wallets to check
        warning_threshold: Health factor threshold for warnings
        critical_threshold: Health factor threshold for critical alerts
        detailed: If True, fetch and format detailed per-asset breakdown

    Returns:
        Formatted message string with all position information
    """
    all_positions = []
    messages = []

    for wallet in wallets:
        if detailed:
            positions = await _engine.get_detailed_positions_for_wallet(wallet.address)
        else:
            positions = await _engine.get_positions_for_wallet(wallet.address)

        if not positions:
            messages.append(format_no_positions(wallet.address))
            continue

        for position in positions:
            all_positions.append(position)
            assessment = assess_health(
                position,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
            )
            if detailed:
                messages.append(format_detailed_position_status(position, assessment))
            else:
                messages.append(format_position_status(position, assessment))

    # Add unified health score if multiple positions
    if len(all_positions) > 1:
        unified = calculate_unified_health_score(all_positions)
        messages.insert(0, format_unified_health_score(unified))

    return "\n\n---\n\n".join(messages) if messages else format_no_wallets()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show basic position status for all monitored wallets."""
    chat_id = update.effective_chat.id

    user_data = await _get_user_wallets_and_thresholds(chat_id)
    if not user_data:
        await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
        return

    wallets, warning_threshold, critical_threshold = user_data

    if not _engine:
        await update.message.reply_text("Monitoring engine not initialized.")
        return

    response = await _build_position_response(
        wallets, warning_threshold, critical_threshold, detailed=False
    )
    await update.message.reply_text(response, parse_mode="Markdown", disable_web_page_preview=True)


async def detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed position breakdown with per-asset information."""
    chat_id = update.effective_chat.id

    user_data = await _get_user_wallets_and_thresholds(chat_id)
    if not user_data:
        await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
        return

    wallets, warning_threshold, critical_threshold = user_data

    if not _engine:
        await update.message.reply_text("Monitoring engine not initialized.")
        return

    response = await _build_position_response(
        wallets, warning_threshold, critical_threshold, detailed=True
    )
    await update.message.reply_text(response, parse_mode="Markdown", disable_web_page_preview=True)


async def simulate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    price_change = None
    if context.args:
        try:
            price_change = float(context.args[0].replace("%", ""))
        except ValueError:
            pass

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user.id)
        )
        wallets = result.scalars().all()

        if not wallets:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

    if not _engine:
        await update.message.reply_text("Monitoring engine not initialized.")
        return

    messages = []

    for wallet in wallets:
        positions = await _engine.get_positions_for_wallet(wallet.address)

        for position in positions:
            short_addr = f"{position.wallet_address[:6]}...{position.wallet_address[-4:]}"
            header = f"*{position.protocol}* | `{short_addr}`\n\n"

            if price_change is not None:
                sim = simulate_price_impact(position, price_change)
                emoji = "💀" if sim.would_liquidate else "✅"
                result = f"{emoji} At {price_change:+.0f}%: HF = "
                result += "LIQUIDATED" if sim.would_liquidate else f"{sim.new_health_factor:.2f}"
                messages.append(header + result)
            else:
                simulations = run_stress_test(position)
                messages.append(header + format_simulation_results(simulations))

            prediction = predict_liquidation(position)
            messages.append(format_prediction(prediction))

    response = "\n\n---\n\n".join(messages) if messages else "No positions to simulate."
    await update.message.reply_text(response, parse_mode="Markdown")


async def protocols_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        format_protocols_list(),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def set_threshold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please provide a threshold value.\n\nUsage: /set_threshold `<value>`\n\nExample: /set_threshold 1.5",
            parse_mode="Markdown",
        )
        return

    try:
        threshold = float(context.args[0])
        if threshold < 1.0 or threshold > 5.0:
            await update.message.reply_text(
                "Threshold must be between 1.0 and 5.0",
            )
            return
    except ValueError:
        await update.message.reply_text(
            "Invalid threshold value. Please provide a number.",
        )
        return

    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id, alert_threshold=threshold)
            session.add(user)
        else:
            user.alert_threshold = threshold

        await session.commit()

    await update.message.reply_text(
        format_threshold_set(threshold),
        parse_mode="Markdown",
    )


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id, alerts_paused=True)
            session.add(user)
        else:
            user.alerts_paused = True

        await session.commit()

    await update.message.reply_text(
        format_alerts_paused(),
        parse_mode="Markdown",
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id, alerts_paused=False)
            session.add(user)
        else:
            user.alerts_paused = False

        await session.commit()

    await update.message.reply_text(
        format_alerts_resumed(),
        parse_mode="Markdown",
    )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user.id)
        )
        wallets = result.scalars().all()

        if not wallets:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        wallet_ids = [w.id for w in wallets]

        result = await session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.wallet_id.in_(wallet_ids))
            .order_by(PositionSnapshot.timestamp.desc())
            .limit(1000)
        )
        snapshots = result.scalars().all()

    if not snapshots:
        await update.message.reply_text("No position history found.")
        return

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "wallet", "protocol", "health_factor", "collateral_usd", "debt_usd"])

    wallet_map = {w.id: w.address for w in wallets}

    for snap in snapshots:
        writer.writerow([
            snap.timestamp.isoformat(),
            wallet_map.get(snap.wallet_id, "unknown"),
            snap.protocol,
            f"{snap.health_factor:.4f}",
            f"{snap.total_collateral_usd:.2f}",
            f"{snap.total_debt_usd:.2f}",
        ])

    output.seek(0)

    await update.message.reply_document(
        document=io.BytesIO(output.getvalue().encode()),
        filename=f"position_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
        caption="📊 Position history export",
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show historical health factor analysis."""
    chat_id = update.effective_chat.id

    async with db.async_session() as session:
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user.id)
        )
        wallets = result.scalars().all()

        if not wallets:
            await update.message.reply_text(format_no_wallets(), parse_mode="Markdown")
            return

        wallet_ids = [w.id for w in wallets]

        # Get aggregate stats
        result = await session.execute(
            select(
                func.avg(PositionSnapshot.health_factor),
                func.min(PositionSnapshot.health_factor),
                func.max(PositionSnapshot.health_factor),
            ).where(PositionSnapshot.wallet_id.in_(wallet_ids))
        )
        stats = result.one()

        avg_hf = stats[0] or 0
        min_hf = stats[1] or 0
        max_hf = stats[2] or 0

        # Get closest call (minimum HF snapshot)
        result = await session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.wallet_id.in_(wallet_ids))
            .order_by(PositionSnapshot.health_factor.asc())
            .limit(1)
        )
        closest = result.scalar_one_or_none()

        closest_hf = closest.health_factor if closest else 0
        closest_date = closest.timestamp.strftime("%Y-%m-%d %H:%M") if closest else "N/A"

    await update.message.reply_text(
        format_historical_summary(avg_hf, min_hf, max_hf, closest_hf, closest_date),
        parse_mode="Markdown",
    )


def create_bot_application() -> Application:
    settings = get_settings()
    application = Application.builder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("detail", detail_command))
    application.add_handler(CommandHandler("simulate", simulate_command))
    application.add_handler(CommandHandler("protocols", protocols_command))
    application.add_handler(CommandHandler("set_threshold", set_threshold_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("history", history_command))

    return application
