import logging
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from sqlalchemy import select, delete
from web3 import Web3

from app.config import get_settings
from app.database import db, User, Wallet
from app.core.engine import MonitoringEngine
from app.core.health import assess_health
from app.core.analytics import simulate_price_impact, predict_liquidation, run_stress_test
from app.bot.messages import (
    format_welcome_message,
    format_help_message,
    format_wallet_added,
    format_wallet_removed,
    format_no_wallets,
    format_no_positions,
    format_position_status,
    format_simulation_results,
    format_prediction,
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
        # Get or create user
        result = await session.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(chat_id=chat_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Check if wallet already exists
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

        # Add wallet
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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if not _engine:
        await update.message.reply_text("Monitoring engine not initialized.")
        return

    settings = get_settings()
    messages = []

    for wallet in wallets:
        positions = await _engine.get_positions_for_wallet(wallet.address)

        if not positions:
            messages.append(format_no_positions(wallet.address))
            continue

        for position in positions:
            assessment = assess_health(
                position,
                warning_threshold=settings.health_factor_threshold,
                critical_threshold=settings.critical_health_factor_threshold,
            )
            messages.append(format_position_status(position, assessment))

    response = "\n\n---\n\n".join(messages) if messages else format_no_wallets()
    await update.message.reply_text(response, parse_mode="Markdown")


async def simulate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Parse price change argument
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
                # Run full stress test
                simulations = run_stress_test(position)
                messages.append(header + format_simulation_results(simulations))

            # Add prediction
            prediction = predict_liquidation(position)
            messages.append(format_prediction(prediction))

    response = "\n\n---\n\n".join(messages) if messages else "No positions to simulate."
    await update.message.reply_text(response, parse_mode="Markdown")


def create_bot_application() -> Application:
    settings = get_settings()
    application = Application.builder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("simulate", simulate_command))

    return application
