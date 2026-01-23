"""Multi-source price oracle service.

This module provides a price aggregation service that fetches prices from
multiple sources (Chainlink, Uniswap TWAP, CoinGecko) with automatic
fallback and validation between sources.
"""

import logging
import aiohttp
from dataclasses import dataclass
from typing import Dict
from datetime import datetime, timedelta
from enum import Enum

from app.services.chainlink import get_chainlink_oracle
from app.services.uniswap_oracle import get_uniswap_oracle

logger = logging.getLogger(__name__)


class PriceSource(Enum):
    CHAINLINK = "chainlink"
    UNISWAP_TWAP = "uniswap_twap"
    COINGECKO = "coingecko"


@dataclass
class UnifiedPrice:
    symbol: str
    price: float
    source: PriceSource
    is_stale: bool
    staleness_seconds: int | None
    timestamp: datetime
    confidence: float  # 0-1 confidence score


class PriceCache:
    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, tuple[UnifiedPrice, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, token_id: str) -> UnifiedPrice | None:
        if token_id in self._cache:
            price, timestamp = self._cache[token_id]
            if datetime.utcnow() - timestamp < self._ttl:
                return price
        return None

    def set(self, token_id: str, price: UnifiedPrice):
        self._cache[token_id] = (price, datetime.utcnow())


class MultiSourcePriceService:
    """
    Multi-source price oracle with the following priority:
    1. Chainlink (primary) - most reliable on-chain source
    2. Uniswap V3 TWAP (fallback) - DEX-based TWAP
    3. CoinGecko API (last resort) - off-chain aggregator
    """

    COINGECKO_API = "https://api.coingecko.com/api/v3"

    TOKEN_ID_MAP = {
        "ETH": "ethereum",
        "WETH": "weth",
        "USDC": "usd-coin",
        "USDT": "tether",
        "DAI": "dai",
        "WBTC": "wrapped-bitcoin",
        "LINK": "chainlink",
        "UNI": "uniswap",
        "AAVE": "aave",
        "CRV": "curve-dao-token",
        "MKR": "maker",
        "SNX": "synthetix-network-token",
        "COMP": "compound-governance-token",
        "YFI": "yearn-finance",
        "SUSHI": "sushi",
        "BAL": "balancer",
        "1INCH": "1inch",
        "ENS": "ethereum-name-service",
        "LDO": "lido-dao",
        "RPL": "rocket-pool",
        "cbETH": "coinbase-wrapped-staked-eth",
        "rETH": "rocket-pool-eth",
        "stETH": "staked-ether",
        "wstETH": "wrapped-steth",
    }

    # Max acceptable deviation between sources (%)
    MAX_DEVIATION_PERCENT = 5.0

    def __init__(self):
        self._cache = PriceCache(ttl_seconds=30)
        self._chainlink = get_chainlink_oracle()
        self._uniswap = get_uniswap_oracle()

    async def get_price(
        self,
        symbol: str,
        validate: bool = True,
    ) -> UnifiedPrice | None:
        """Get price from best available source with validation."""
        symbol = symbol.upper()

        # Check cache
        cached = self._cache.get(symbol)
        if cached is not None:
            return cached

        # Try Chainlink first (highest confidence)
        chainlink_price = await self._get_chainlink_price(symbol)
        if chainlink_price and not chainlink_price.is_stale:
            # Optionally validate against secondary source
            if validate:
                await self._validate_price(symbol, chainlink_price.price)
            return chainlink_price

        # Try Uniswap TWAP (medium confidence)
        uniswap_price = await self._get_uniswap_price(symbol)
        if uniswap_price:
            # Validate deviation from spot
            if uniswap_price.confidence > 0.7:
                return uniswap_price

        # Fall back to CoinGecko (lower confidence for on-chain use)
        coingecko_price = await self._get_coingecko_price(symbol)
        if coingecko_price:
            return coingecko_price

        # If Chainlink was stale but available, use it as last resort
        if chainlink_price:
            logger.warning(f"Using stale Chainlink price for {symbol}")
            return chainlink_price

        logger.error(f"No price available for {symbol}")
        return None

    async def _get_chainlink_price(self, symbol: str) -> UnifiedPrice | None:
        try:
            price_data = await self._chainlink.get_price(symbol)
            if price_data:
                unified = UnifiedPrice(
                    symbol=symbol,
                    price=price_data.price,
                    source=PriceSource.CHAINLINK,
                    is_stale=price_data.is_stale,
                    staleness_seconds=price_data.staleness_seconds,
                    timestamp=price_data.updated_at,
                    confidence=0.95 if not price_data.is_stale else 0.7,
                )
                self._cache.set(symbol, unified)
                return unified
        except Exception as e:
            logger.error(f"Chainlink error for {symbol}: {e}")
        return None

    async def _get_uniswap_price(self, symbol: str) -> UnifiedPrice | None:
        try:
            # First get ETH price from Chainlink for USD conversion
            eth_price = await self._chainlink.get_price("ETH")
            if eth_price:
                await self._uniswap.set_eth_price_usd(eth_price.price)

            twap_data = await self._uniswap.get_twap(symbol)
            if twap_data:
                # Lower confidence if high deviation from spot
                confidence = 0.85 if twap_data.deviation_percent < 2 else 0.7

                unified = UnifiedPrice(
                    symbol=symbol,
                    price=twap_data.price,
                    source=PriceSource.UNISWAP_TWAP,
                    is_stale=False,
                    staleness_seconds=None,
                    timestamp=twap_data.timestamp,
                    confidence=confidence,
                )
                self._cache.set(symbol, unified)
                return unified
        except Exception as e:
            logger.error(f"Uniswap TWAP error for {symbol}: {e}")
        return None

    async def _get_coingecko_price(self, symbol: str) -> UnifiedPrice | None:
        token_id = self.TOKEN_ID_MAP.get(symbol)
        if not token_id:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.COINGECKO_API}/simple/price"
                params = {"ids": token_id, "vs_currencies": "usd"}
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get(token_id, {}).get("usd")
                        if price:
                            unified = UnifiedPrice(
                                symbol=symbol,
                                price=price,
                                source=PriceSource.COINGECKO,
                                is_stale=False,
                                staleness_seconds=None,
                                timestamp=datetime.utcnow(),
                                confidence=0.75,  # Lower confidence for off-chain
                            )
                            self._cache.set(symbol, unified)
                            return unified
        except Exception as e:
            logger.error(f"CoinGecko error for {symbol}: {e}")
        return None

    async def _validate_price(self, symbol: str, price: float) -> bool:
        """Validate price against secondary sources."""
        # Try to get a second source for validation
        uniswap_price = await self._uniswap.get_spot_price(symbol)
        if uniswap_price:
            deviation = abs(price - uniswap_price) / price * 100
            if deviation > self.MAX_DEVIATION_PERCENT:
                logger.warning(
                    f"Price deviation for {symbol}: Chainlink={price}, "
                    f"Uniswap={uniswap_price}, deviation={deviation:.2f}%"
                )
                return False
        return True

    async def get_prices(self, symbols: list[str]) -> Dict[str, UnifiedPrice]:
        """Get prices for multiple symbols."""
        results = {}
        for symbol in symbols:
            price = await self.get_price(symbol)
            if price:
                results[symbol.upper()] = price
        return results

    async def get_eth_price(self) -> float | None:
        """Convenience method for ETH price."""
        price = await self.get_price("ETH")
        return price.price if price else None

    async def get_gas_price_gwei(self) -> float | None:
        """Get current gas price in Gwei."""
        try:
            from app.services.rpc import get_web3
            web3 = get_web3()
            gas_price = await web3.eth.gas_price
            return gas_price / 1e9  # Convert to Gwei
        except Exception as e:
            logger.error(f"Error fetching gas price: {e}")
            return None


# Legacy compatibility - keep old interface working
class PriceService(MultiSourcePriceService):
    """Alias for backward compatibility."""
    pass


# Singleton
_price_service: MultiSourcePriceService | None = None


def get_price_service() -> MultiSourcePriceService:
    global _price_service
    if _price_service is None:
        _price_service = MultiSourcePriceService()
    return _price_service
