from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.protocols.base import ProtocolAdapter, Position
from app.config import get_settings

# Compound V3 Comet USDC addresses per chain
COMPOUND_V3_COMET_ADDRESSES = {
    "ethereum": "0xc3d688B66703497DAA19211EEdff47f25384cdc3",
    "arbitrum": "0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
    "base": "0xb125E6687d4313864e53df431d5425969c15Eb2F",
    "optimism": "0x2e44e174f7D53F0212823acC11C01A11d58c5bCB",
}

COMET_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "borrowBalanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
        ],
        "name": "collateralBalanceOf",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "isLiquidatable",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint8", "name": "i", "type": "uint8"}],
        "name": "getAssetInfo",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint8", "name": "offset", "type": "uint8"},
                    {"internalType": "address", "name": "asset", "type": "address"},
                    {"internalType": "address", "name": "priceFeed", "type": "address"},
                    {"internalType": "uint64", "name": "scale", "type": "uint64"},
                    {"internalType": "uint64", "name": "borrowCollateralFactor", "type": "uint64"},
                    {"internalType": "uint64", "name": "liquidateCollateralFactor", "type": "uint64"},
                    {"internalType": "uint64", "name": "liquidationFactor", "type": "uint64"},
                    {"internalType": "uint128", "name": "supplyCap", "type": "uint128"},
                ],
                "internalType": "struct CometCore.AssetInfo",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "numAssets",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "priceFeed", "type": "address"}],
        "name": "getPrice",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseTokenPriceFeed",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class CompoundV3Adapter(ProtocolAdapter):
    def __init__(self, chain: str = "ethereum", web3: AsyncWeb3 | None = None, comet_address: str | None = None):
        self._chain = chain.lower()
        if self._chain not in COMPOUND_V3_COMET_ADDRESSES:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(COMPOUND_V3_COMET_ADDRESSES.keys())}")

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

        self._comet_address = comet_address or COMPOUND_V3_COMET_ADDRESSES[self._chain]
        self._comet_contract = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(self._comet_address),
            abi=COMET_ABI,
        )

    @property
    def name(self) -> str:
        chain_display = self._chain.capitalize()
        return f"Compound V3 ({chain_display})"

    @property
    def chain(self) -> str:
        return self._chain

    async def get_position(self, wallet_address: str) -> Position | None:
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)

            # Get borrow balance (in base token - USDC)
            borrow_balance = await self._comet_contract.functions.borrowBalanceOf(
                checksum_address
            ).call()
            borrow_balance_usd = borrow_balance / 1e6  # USDC has 6 decimals

            # Get supply balance (base token)
            supply_balance = await self._comet_contract.functions.balanceOf(
                checksum_address
            ).call()
            supply_balance_usd = supply_balance / 1e6

            # Get collateral balances and calculate total collateral value
            num_assets = await self._comet_contract.functions.numAssets().call()
            total_collateral_usd = 0.0
            avg_liquidation_factor = 0.0

            for i in range(num_assets):
                asset_info = await self._comet_contract.functions.getAssetInfo(i).call()
                asset_address = asset_info[1]
                price_feed = asset_info[2]
                scale = asset_info[3]
                liquidate_collateral_factor = asset_info[5] / 1e18

                collateral_balance = await self._comet_contract.functions.collateralBalanceOf(
                    checksum_address, asset_address
                ).call()

                if collateral_balance > 0:
                    price = await self._comet_contract.functions.getPrice(price_feed).call()
                    # Price is in 8 decimals, scale converts to base units
                    collateral_value = (collateral_balance * price) / (scale * 1e8)
                    total_collateral_usd += collateral_value
                    avg_liquidation_factor = max(avg_liquidation_factor, liquidate_collateral_factor)

            if total_collateral_usd == 0 and borrow_balance_usd == 0 and supply_balance_usd == 0:
                return None

            # Calculate health factor
            # In Compound V3, health factor = (collateral * liquidation_factor) / debt
            if borrow_balance_usd > 0 and avg_liquidation_factor > 0:
                health_factor = (total_collateral_usd * avg_liquidation_factor) / borrow_balance_usd
            else:
                health_factor = float("inf")

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=total_collateral_usd + supply_balance_usd,
                total_debt_usd=borrow_balance_usd,
                liquidation_threshold=avg_liquidation_factor,
                available_borrows_usd=0.0,
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

    async def is_liquidatable(self, wallet_address: str) -> bool:
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            return await self._comet_contract.functions.isLiquidatable(checksum_address).call()
        except Exception:
            return False
