"""Base protocol adapter interface and data models.

This module defines the abstract interface for protocol adapters (Aave, Compound)
and the data models for representing lending positions with collateral and debt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Asset:
    """Base asset with balance and price information."""
    symbol: str
    address: str
    balance: float              # Raw token amount (e.g., 3.45 ETH)
    balance_usd: float          # USD value
    price_usd: float            # Current USD price per token
    decimals: int = 18          # Token decimals


@dataclass
class CollateralAsset(Asset):
    """Asset supplied as collateral in a lending position."""
    is_collateral_enabled: bool = True  # Whether used as collateral for borrows
    ltv: float = 0.0                    # Loan-to-Value ratio (0.80 = 80%)
    liquidation_threshold: float = 0.0  # Threshold before liquidation (0.825 = 82.5%)
    supply_apy: float | None = None     # Current supply APY (0.032 = 3.2%)


@dataclass
class DebtAsset(Asset):
    """Asset borrowed as debt in a lending position."""
    interest_rate_mode: str = "variable"       # "variable" or "stable"
    borrow_apy: float = 0.0                    # Current borrow APY
    stable_borrow_apy: float | None = None     # Stable rate if applicable (Aave only)
    accrued_interest: float | None = None      # Interest since last interaction


@dataclass
class Position:
    """Lending position with collateral and debt assets."""
    protocol: str
    wallet_address: str
    health_factor: float
    collateral_assets: List[CollateralAsset]
    debt_assets: List[DebtAsset]
    total_collateral_usd: float
    total_debt_usd: float
    liquidation_threshold: float  # Weighted average across collaterals
    available_borrows_usd: float
    chain: str = "ethereum"       # Chain name: "ethereum", "arbitrum", "base", "optimism"
    net_apy: float | None = None  # Net APY (supply - borrow weighted)


class ProtocolAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the protocol name (e.g., 'Aave V3 (Ethereum)')."""
        pass

    @property
    @abstractmethod
    def chain(self) -> str:
        """Return the chain name for this adapter."""
        pass

    @abstractmethod
    async def get_position(self, wallet_address: str) -> Position | None:
        """Get basic position data (backward compatible)."""
        pass

    @abstractmethod
    async def get_detailed_position(self, wallet_address: str) -> Position | None:
        """Get detailed position with per-asset breakdown."""
        pass

    @abstractmethod
    async def get_health_factor(self, wallet_address: str) -> float | None:
        pass

    @abstractmethod
    async def get_liquidation_threshold(self, wallet_address: str) -> float | None:
        pass

    @abstractmethod
    async def has_position(self, wallet_address: str) -> bool:
        pass
