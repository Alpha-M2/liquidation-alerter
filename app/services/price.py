import aiohttp
from typing import Dict
from functools import lru_cache
from datetime import datetime, timedelta


class PriceCache:
    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, tuple[float, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, token_id: str) -> float | None:
        if token_id in self._cache:
            price, timestamp = self._cache[token_id]
            if datetime.utcnow() - timestamp < self._ttl:
                return price
        return None

    def set(self, token_id: str, price: float):
        self._cache[token_id] = (price, datetime.utcnow())


class PriceService:
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

    def __init__(self):
        self._cache = PriceCache(ttl_seconds=60)

    async def get_price(self, symbol: str) -> float | None:
        cached = self._cache.get(symbol)
        if cached is not None:
            return cached

        token_id = self.TOKEN_ID_MAP.get(symbol.upper())
        if not token_id:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.COINGECKO_API}/simple/price"
                params = {"ids": token_id, "vs_currencies": "usd"}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get(token_id, {}).get("usd")
                        if price:
                            self._cache.set(symbol, price)
                            return price
        except Exception:
            pass
        return None

    async def get_prices(self, symbols: list[str]) -> Dict[str, float]:
        result = {}
        missing = []

        for symbol in symbols:
            cached = self._cache.get(symbol)
            if cached is not None:
                result[symbol] = cached
            else:
                missing.append(symbol)

        if missing:
            token_ids = [
                self.TOKEN_ID_MAP.get(s.upper())
                for s in missing
                if s.upper() in self.TOKEN_ID_MAP
            ]
            token_ids = [t for t in token_ids if t]

            if token_ids:
                try:
                    async with aiohttp.ClientSession() as session:
                        url = f"{self.COINGECKO_API}/simple/price"
                        params = {"ids": ",".join(token_ids), "vs_currencies": "usd"}
                        async with session.get(url, params=params) as response:
                            if response.status == 200:
                                data = await response.json()
                                for symbol in missing:
                                    token_id = self.TOKEN_ID_MAP.get(symbol.upper())
                                    if token_id and token_id in data:
                                        price = data[token_id].get("usd")
                                        if price:
                                            self._cache.set(symbol, price)
                                            result[symbol] = price
                except Exception:
                    pass

        return result


@lru_cache
def get_price_service() -> PriceService:
    return PriceService()
