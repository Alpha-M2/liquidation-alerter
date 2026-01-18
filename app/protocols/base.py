from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Asset:
    symbol: str
    address: str
    balance: float
    balance_usd: float
    price_usd: float


@dataclass
class Position:
    protocol: str
    wallet_address: str
    health_factor: float
    collateral_assets: List[Asset]
    debt_assets: List[Asset]
    total_collateral_usd: float
    total_debt_usd: float
    liquidation_threshold: float
    available_borrows_usd: float


class ProtocolAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def get_position(self, wallet_address: str) -> Position | None:
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
