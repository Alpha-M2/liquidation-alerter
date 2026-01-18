from web3 import AsyncWeb3

from app.protocols.base import ProtocolAdapter, Position, Asset
from app.services.rpc import get_web3

# Aave V2 Lending Pool on Ethereum Mainnet
AAVE_V2_LENDING_POOL = "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9"
AAVE_V2_PROTOCOL_DATA_PROVIDER = "0x057835Ad21a177dbdd3090bB1CAE03EaCF78Fc6d"

LENDING_POOL_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserAccountData",
        "outputs": [
            {"internalType": "uint256", "name": "totalCollateralETH", "type": "uint256"},
            {"internalType": "uint256", "name": "totalDebtETH", "type": "uint256"},
            {"internalType": "uint256", "name": "availableBorrowsETH", "type": "uint256"},
            {"internalType": "uint256", "name": "currentLiquidationThreshold", "type": "uint256"},
            {"internalType": "uint256", "name": "ltv", "type": "uint256"},
            {"internalType": "uint256", "name": "healthFactor", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

DATA_PROVIDER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserReservesData",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "underlyingAsset", "type": "address"},
                    {"internalType": "uint256", "name": "scaledATokenBalance", "type": "uint256"},
                    {"internalType": "bool", "name": "usageAsCollateralEnabledOnUser", "type": "bool"},
                    {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
                    {"internalType": "uint256", "name": "scaledVariableDebt", "type": "uint256"},
                    {"internalType": "uint256", "name": "principalStableDebt", "type": "uint256"},
                    {"internalType": "uint256", "name": "stableBorrowLastUpdateTimestamp", "type": "uint256"},
                ],
                "internalType": "struct IUiPoolDataProviderV2.UserReserveData[]",
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"internalType": "uint256", "name": "availableLiquidity", "type": "uint256"},
            {"internalType": "uint256", "name": "totalStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "totalVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "averageStableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityIndex", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowIndex", "type": "uint256"},
            {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class AaveV2Adapter(ProtocolAdapter):
    def __init__(self, web3: AsyncWeb3 | None = None):
        self._web3 = web3 or get_web3()
        self._lending_pool = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(AAVE_V2_LENDING_POOL),
            abi=LENDING_POOL_ABI,
        )

    @property
    def name(self) -> str:
        return "Aave V2"

    @property
    def protocol_url(self) -> str:
        return "https://app.aave.com"

    async def get_position(self, wallet_address: str) -> Position | None:
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            data = await self._lending_pool.functions.getUserAccountData(
                checksum_address
            ).call()

            # Aave V2 returns values in ETH (18 decimals)
            total_collateral_eth = data[0] / 1e18
            total_debt_eth = data[1] / 1e18
            available_borrows_eth = data[2] / 1e18
            liquidation_threshold = data[3] / 1e4  # Percentage in basis points
            health_factor = data[5] / 1e18 if data[5] < 2**255 else float("inf")

            if total_collateral_eth == 0 and total_debt_eth == 0:
                return None

            # Note: Values are in ETH, need price conversion for USD
            # For now, we'll use a placeholder ETH price - this will be enhanced
            # with the Chainlink oracle integration
            eth_price_usd = 2000.0  # Placeholder - will be replaced by oracle

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=total_collateral_eth * eth_price_usd,
                total_debt_usd=total_debt_eth * eth_price_usd,
                liquidation_threshold=liquidation_threshold,
                available_borrows_usd=available_borrows_eth * eth_price_usd,
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
