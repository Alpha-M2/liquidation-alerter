"""Chainlink price oracle integration.

This module provides access to Chainlink price feeds on Ethereum mainnet
for reliable, decentralized price data with staleness detection.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict
from web3 import AsyncWeb3

from app.services.rpc import get_web3

logger = logging.getLogger(__name__)

# Chainlink Price Feed Addresses on Ethereum Mainnet
CHAINLINK_FEEDS = {
    "ETH": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",  # ETH/USD
    "WETH": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",  # Same as ETH
    "BTC": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",  # BTC/USD
    "WBTC": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",  # Same as BTC
    "USDC": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",  # USDC/USD
    "USDT": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",  # USDT/USD
    "DAI": "0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9",  # DAI/USD
    "LINK": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",  # LINK/USD
    "UNI": "0x553303d460EE0afB37EdFf9bE42922D8FF63220e",  # UNI/USD
    "AAVE": "0x547a514d5e3769680Ce22B2361c10Ea13619e8a9",  # AAVE/USD
    "CRV": "0xCd627aA160A6fA45Eb793D19286F3a0f93B8f5b6",  # CRV/USD
    "MKR": "0xec1D1B3b0443256cc3860e24a46F108e699cF2Ba",  # MKR/USD
    "COMP": "0xdbd020CAeF83eFd542f4De03864e8c6e7E5E2eFF",  # COMP/USD
    "SNX": "0xDC3EA94CD0AC27d9A86C180091e7f78C683d3699",  # SNX/USD
    "YFI": "0xA027702dbb89fbd58e2903F4A5c67b28eeE06eB1",  # YFI/USD
    "SUSHI": "0xCc70F09A6CC17553b2E31954cD36E4A2d89501f7",  # SUSHI/USD
    "1INCH": "0xc929ad75B72593967DE83E7F7cdA0493458261D9",  # 1INCH/USD
    "ENS": "0x5C00128d4d1c2F4f652C267d7bcdD7Ac99C16E16",  # ENS/USD
    "LDO": "0x4e844125952D32AcdF339BE976c98fe6D1f30389",  # LDO/USD
    "RPL": "0x4E155eD98aFE9034b7A5962f6C84c86d869daA9d",  # RPL/USD
    "stETH": "0xCfE54B5cD566aB89272946F602D76Ea879CAb4a8",  # stETH/USD
    "wstETH": "0x164b276057258d81941072EDA0f37A78E8b8C6bB",  # wstETH/stETH ratio
    "cbETH": "0xF017fcB346A1885194689bA23Eff2fE6fA5C483b",  # cbETH/ETH
    "rETH": "0x536218f9E9Eb48863970252233c8F271f554C2d0",  # rETH/ETH
}

# Staleness thresholds (in seconds) for different asset types
STALENESS_THRESHOLDS = {
    "default": 3600,  # 1 hour for most assets
    "stablecoins": 86400,  # 24 hours for stablecoins (USDC, USDT, DAI)
    "volatile": 1800,  # 30 minutes for volatile assets
}

CHAINLINK_AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class PriceData:
    symbol: str
    price: float
    decimals: int
    updated_at: datetime
    round_id: int
    is_stale: bool
    staleness_seconds: int
    source: str = "chainlink"


class ChainlinkOracle:
    STABLECOINS = {"USDC", "USDT", "DAI", "FRAX", "LUSD", "GUSD"}
    VOLATILE_ASSETS = {"BTC", "WBTC", "ETH", "WETH"}

    def __init__(self, web3: AsyncWeb3 | None = None):
        self._web3 = web3 or get_web3()
        self._price_cache: Dict[str, PriceData] = {}
        self._cache_ttl = timedelta(seconds=30)

    def _get_staleness_threshold(self, symbol: str) -> int:
        if symbol.upper() in self.STABLECOINS:
            return STALENESS_THRESHOLDS["stablecoins"]
        if symbol.upper() in self.VOLATILE_ASSETS:
            return STALENESS_THRESHOLDS["volatile"]
        return STALENESS_THRESHOLDS["default"]

    def _is_price_stale(self, updated_at: datetime, symbol: str) -> tuple[bool, int]:
        threshold = self._get_staleness_threshold(symbol)
        age = (datetime.utcnow() - updated_at).total_seconds()
        return age > threshold, int(age)

    async def get_price(self, symbol: str) -> PriceData | None:
        symbol = symbol.upper()

        # Check cache first
        if symbol in self._price_cache:
            cached = self._price_cache[symbol]
            cache_age = datetime.utcnow() - cached.updated_at
            if cache_age < self._cache_ttl:
                return cached

        feed_address = CHAINLINK_FEEDS.get(symbol)
        if not feed_address:
            logger.warning(f"No Chainlink feed found for {symbol}")
            return None

        try:
            contract = self._web3.eth.contract(
                address=AsyncWeb3.to_checksum_address(feed_address),
                abi=CHAINLINK_AGGREGATOR_ABI,
            )

            # Get latest round data
            round_data = await contract.functions.latestRoundData().call()
            decimals = await contract.functions.decimals().call()

            round_id = round_data[0]
            answer = round_data[1]
            updated_at_timestamp = round_data[3]

            # Convert to standard format
            price = answer / (10**decimals)
            updated_at = datetime.utcfromtimestamp(updated_at_timestamp)

            # Check staleness
            is_stale, staleness_seconds = self._is_price_stale(updated_at, symbol)

            if is_stale:
                logger.warning(
                    f"Chainlink price for {symbol} is stale "
                    f"(last update: {staleness_seconds}s ago)"
                )

            price_data = PriceData(
                symbol=symbol,
                price=price,
                decimals=decimals,
                updated_at=updated_at,
                round_id=round_id,
                is_stale=is_stale,
                staleness_seconds=staleness_seconds,
                source="chainlink",
            )

            # Update cache
            self._price_cache[symbol] = price_data

            return price_data

        except Exception as e:
            logger.error(f"Error fetching Chainlink price for {symbol}: {e}")
            return None

    async def get_prices(self, symbols: list[str]) -> Dict[str, PriceData]:
        results = {}
        for symbol in symbols:
            price_data = await self.get_price(symbol)
            if price_data:
                results[symbol.upper()] = price_data
        return results

    async def get_eth_price(self) -> float | None:
        price_data = await self.get_price("ETH")
        return price_data.price if price_data else None

    async def validate_price(
        self,
        symbol: str,
        price: float,
        max_deviation_percent: float = 10.0,
    ) -> bool:
        """
        Validate a price against Chainlink as reference.
        Returns True if price is within acceptable deviation.
        """
        chainlink_price = await self.get_price(symbol)
        if not chainlink_price:
            return True  # Can't validate, assume OK

        deviation = abs(price - chainlink_price.price) / chainlink_price.price * 100

        if deviation > max_deviation_percent:
            logger.warning(
                f"Price deviation for {symbol}: {deviation:.2f}% "
                f"(input: {price}, Chainlink: {chainlink_price.price})"
            )
            return False

        return True

    def get_feed_address(self, symbol: str) -> str | None:
        return CHAINLINK_FEEDS.get(symbol.upper())

    def is_supported(self, symbol: str) -> bool:
        return symbol.upper() in CHAINLINK_FEEDS


# Singleton instance
_chainlink_oracle: ChainlinkOracle | None = None


def get_chainlink_oracle() -> ChainlinkOracle:
    global _chainlink_oracle
    if _chainlink_oracle is None:
        _chainlink_oracle = ChainlinkOracle()
    return _chainlink_oracle
