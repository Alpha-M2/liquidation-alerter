import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict
from web3 import AsyncWeb3

from app.services.rpc import get_web3

logger = logging.getLogger(__name__)

# Uniswap V3 Factory and common pool addresses on Ethereum Mainnet
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# Common Uniswap V3 pools (token/WETH or token/USDC)
UNISWAP_V3_POOLS = {
    # Token: (pool_address, quote_token, fee_tier, token0_is_base)
    "WETH-USDC": ("0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640", "USDC", 500, False),  # USDC is token0
    "WETH-USDT": ("0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36", "USDT", 3000, True),
    "WBTC-WETH": ("0xCBCdF9626bC03E24f779434178A73a0B4bad62eD", "WETH", 3000, True),
    "LINK-WETH": ("0xa6Cc3C2531FdaA6Ae1A3CA84c2855806728693e8", "WETH", 3000, True),
    "UNI-WETH": ("0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801", "WETH", 3000, True),
    "AAVE-WETH": ("0x5aB53EE1d50eeF2C1DD3d5402789cd27bB52c1bB", "WETH", 3000, True),
    "MKR-WETH": ("0xe8c6c9227491C0a8156A0106A0204d881BB7E531", "WETH", 3000, True),
    "COMP-WETH": ("0xea4Ba4CE14fdd287f380b55419B1C5b6c3f22ab6", "WETH", 3000, True),
    "CRV-WETH": ("0x919Fa96e88d67499339577Fa202345436bcDaf79", "WETH", 10000, True),
    "SNX-WETH": ("0xE28e69Df0f89E96bd5a0b66e20c18A0f4D78c6df", "WETH", 3000, True),
    "LDO-WETH": ("0xa3f558aEbAecAf0e11cA4b2199cC5Ed341edfd74", "WETH", 3000, True),
}

# Token addresses
TOKEN_ADDRESSES = {
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "DAI": "0x6B175474E89094C44Da98b954EescdeCB5b42A3",
    "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
}

UNISWAP_V3_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint32[]", "name": "secondsAgos", "type": "uint32[]"}],
        "name": "observe",
        "outputs": [
            {"internalType": "int56[]", "name": "tickCumulatives", "type": "int56[]"},
            {"internalType": "uint160[]", "name": "secondsPerLiquidityCumulativeX128s", "type": "uint160[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class TWAPPrice:
    symbol: str
    price: float
    twap_seconds: int
    spot_price: float
    deviation_percent: float
    pool_address: str
    liquidity: int
    timestamp: datetime
    source: str = "uniswap_v3_twap"


class UniswapV3Oracle:
    """Uniswap V3 TWAP Oracle as fallback for Chainlink."""

    Q96 = 2**96
    DEFAULT_TWAP_SECONDS = 1800  # 30 minutes

    def __init__(self, web3: AsyncWeb3 | None = None):
        self._web3 = web3 or get_web3()
        self._eth_price_usd: float | None = None

    def _tick_to_price(self, tick: int, token0_decimals: int = 18, token1_decimals: int = 18) -> float:
        """Convert Uniswap V3 tick to price."""
        return (1.0001**tick) * (10 ** (token0_decimals - token1_decimals))

    def _sqrt_price_x96_to_price(
        self,
        sqrt_price_x96: int,
        token0_decimals: int = 18,
        token1_decimals: int = 18,
    ) -> float:
        """Convert sqrtPriceX96 to actual price."""
        price = (sqrt_price_x96 / self.Q96) ** 2
        return price * (10 ** (token0_decimals - token1_decimals))

    async def set_eth_price_usd(self, price: float):
        """Set ETH/USD price for converting WETH-denominated prices."""
        self._eth_price_usd = price

    async def get_twap(
        self,
        symbol: str,
        twap_seconds: int = DEFAULT_TWAP_SECONDS,
    ) -> TWAPPrice | None:
        """Get TWAP price for a token."""
        pool_key = f"{symbol}-WETH"
        pool_data = UNISWAP_V3_POOLS.get(pool_key)

        if not pool_data:
            # Try USDC pair
            pool_key = f"{symbol}-USDC"
            pool_data = UNISWAP_V3_POOLS.get(pool_key)

        if not pool_data:
            logger.warning(f"No Uniswap V3 pool found for {symbol}")
            return None

        pool_address, quote_token, fee_tier, token0_is_base = pool_data

        try:
            pool = self._web3.eth.contract(
                address=AsyncWeb3.to_checksum_address(pool_address),
                abi=UNISWAP_V3_POOL_ABI,
            )

            # Get current slot0 for spot price
            slot0 = await pool.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            current_tick = slot0[1]

            # Get TWAP using observe
            seconds_agos = [twap_seconds, 0]
            observations = await pool.functions.observe(seconds_agos).call()
            tick_cumulatives = observations[0]

            # Calculate TWAP tick
            twap_tick = (tick_cumulatives[1] - tick_cumulatives[0]) // twap_seconds

            # Get pool liquidity
            liquidity = await pool.functions.liquidity().call()

            # Determine decimals based on tokens
            if quote_token == "USDC" or quote_token == "USDT":
                quote_decimals = 6
            else:
                quote_decimals = 18

            base_decimals = 18  # Most tokens are 18 decimals
            if symbol == "WBTC":
                base_decimals = 8
            elif symbol in ["USDC", "USDT"]:
                base_decimals = 6

            # Calculate prices
            spot_price = self._tick_to_price(current_tick, base_decimals, quote_decimals)
            twap_price = self._tick_to_price(twap_tick, base_decimals, quote_decimals)

            # Invert if needed (token0 is quote)
            if not token0_is_base:
                spot_price = 1 / spot_price if spot_price > 0 else 0
                twap_price = 1 / twap_price if twap_price > 0 else 0

            # Convert to USD if quote is WETH
            if quote_token == "WETH" and self._eth_price_usd:
                spot_price *= self._eth_price_usd
                twap_price *= self._eth_price_usd

            # Calculate deviation
            deviation = abs(spot_price - twap_price) / twap_price * 100 if twap_price > 0 else 0

            return TWAPPrice(
                symbol=symbol,
                price=twap_price,
                twap_seconds=twap_seconds,
                spot_price=spot_price,
                deviation_percent=deviation,
                pool_address=pool_address,
                liquidity=liquidity,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Error fetching Uniswap TWAP for {symbol}: {e}")
            return None

    async def get_spot_price(self, symbol: str) -> float | None:
        """Get current spot price (not TWAP)."""
        twap_data = await self.get_twap(symbol, twap_seconds=1)
        return twap_data.spot_price if twap_data else None

    def is_supported(self, symbol: str) -> bool:
        """Check if we have a Uniswap pool for this symbol."""
        return (
            f"{symbol}-WETH" in UNISWAP_V3_POOLS
            or f"{symbol}-USDC" in UNISWAP_V3_POOLS
            or symbol == "WETH"
        )


# Singleton
_uniswap_oracle: UniswapV3Oracle | None = None


def get_uniswap_oracle() -> UniswapV3Oracle:
    global _uniswap_oracle
    if _uniswap_oracle is None:
        _uniswap_oracle = UniswapV3Oracle()
    return _uniswap_oracle
