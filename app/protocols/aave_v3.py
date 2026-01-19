from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.protocols.base import ProtocolAdapter, Position
from app.config import get_settings

# Aave V3 Pool addresses per chain
AAVE_V3_POOL_ADDRESSES = {
    "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    "base": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
    "optimism": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
}

POOL_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserAccountData",
        "outputs": [
            {"internalType": "uint256", "name": "totalCollateralBase", "type": "uint256"},
            {"internalType": "uint256", "name": "totalDebtBase", "type": "uint256"},
            {"internalType": "uint256", "name": "availableBorrowsBase", "type": "uint256"},
            {"internalType": "uint256", "name": "currentLiquidationThreshold", "type": "uint256"},
            {"internalType": "uint256", "name": "ltv", "type": "uint256"},
            {"internalType": "uint256", "name": "healthFactor", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


class AaveV3Adapter(ProtocolAdapter):
    def __init__(self, chain: str = "ethereum", web3: AsyncWeb3 | None = None):
        self._chain = chain.lower()
        if self._chain not in AAVE_V3_POOL_ADDRESSES:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(AAVE_V3_POOL_ADDRESSES.keys())}")

        settings = get_settings()

        # Get chain-specific RPC URL from settings
        rpc_url = getattr(settings, f"{self._chain}_rpc_url", None) or settings.rpc_url

        if web3:
            self._web3 = web3
        else:
            self._web3 = AsyncWeb3(
                AsyncHTTPProvider(rpc_url),
                modules={"eth": (AsyncEth,)},
            )

        pool_address = AAVE_V3_POOL_ADDRESSES[self._chain]
        self._pool_contract = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(pool_address),
            abi=POOL_ABI,
        )

    @property
    def name(self) -> str:
        chain_display = self._chain.capitalize()
        return f"Aave V3 ({chain_display})"

    @property
    def chain(self) -> str:
        return self._chain

    async def get_position(self, wallet_address: str) -> Position | None:
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            data = await self._pool_contract.functions.getUserAccountData(
                checksum_address
            ).call()

            total_collateral_base = data[0] / 1e8  # Aave uses 8 decimals for base currency
            total_debt_base = data[1] / 1e8
            available_borrows_base = data[2] / 1e8
            liquidation_threshold = data[3] / 1e4  # Percentage in basis points
            health_factor = data[5] / 1e18 if data[5] < 2**255 else float("inf")

            if total_collateral_base == 0 and total_debt_base == 0:
                return None

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=total_collateral_base,
                total_debt_usd=total_debt_base,
                liquidation_threshold=liquidation_threshold,
                available_borrows_usd=available_borrows_base,
            )
        except Exception:
            return None

    async def get_health_factor(self, wallet_address: str) -> float | None:
        position = await self.get_position(wallet_address)
        return position.health_factor if position else None

    async def get_liquidation_threshold(self, wallet_address: str) -> float | None:
        position = await self.get_position(wallet_address)
        return position.liquidation_threshold if position else None

    async def has_position(self, wallet_address: str) -> bool:
        position = await self.get_position(wallet_address)
        return position is not None and (
            position.total_collateral_usd > 0 or position.total_debt_usd > 0
        )
