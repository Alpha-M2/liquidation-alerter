from typing import List
from web3 import AsyncWeb3

from app.protocols.base import ProtocolAdapter, Position, Asset
from app.services.rpc import get_web3

# Morpho Blue on Ethereum Mainnet (newest version)
MORPHO_BLUE = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"

# Morpho Aave V2 Optimizer (legacy)
MORPHO_AAVE_V2 = "0x777777c9898D384F785Ee44Acfe945efDFf5f3E0"

# Morpho Compound V2 Optimizer (legacy)
MORPHO_COMPOUND_V2 = "0x8888882f8f843896699869179fB6E4f7e3B58888"

MORPHO_BLUE_ABI = [
    {
        "inputs": [
            {"internalType": "Id", "name": "id", "type": "bytes32"},
            {"internalType": "address", "name": "user", "type": "address"},
        ],
        "name": "position",
        "outputs": [
            {"internalType": "uint256", "name": "supplyShares", "type": "uint256"},
            {"internalType": "uint128", "name": "borrowShares", "type": "uint128"},
            {"internalType": "uint128", "name": "collateral", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "Id", "name": "id", "type": "bytes32"}],
        "name": "market",
        "outputs": [
            {"internalType": "uint128", "name": "totalSupplyAssets", "type": "uint128"},
            {"internalType": "uint128", "name": "totalSupplyShares", "type": "uint128"},
            {"internalType": "uint128", "name": "totalBorrowAssets", "type": "uint128"},
            {"internalType": "uint128", "name": "totalBorrowShares", "type": "uint128"},
            {"internalType": "uint128", "name": "lastUpdate", "type": "uint128"},
            {"internalType": "uint128", "name": "fee", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "Id", "name": "id", "type": "bytes32"}],
        "name": "idToMarketParams",
        "outputs": [
            {"internalType": "address", "name": "loanToken", "type": "address"},
            {"internalType": "address", "name": "collateralToken", "type": "address"},
            {"internalType": "address", "name": "oracle", "type": "address"},
            {"internalType": "address", "name": "irm", "type": "address"},
            {"internalType": "uint256", "name": "lltv", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

MORPHO_AAVE_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "_poolToken", "type": "address"},
            {"internalType": "address", "name": "_user", "type": "address"},
        ],
        "name": "getCurrentSupplyBalanceInOf",
        "outputs": [
            {"internalType": "uint256", "name": "balanceInP2P", "type": "uint256"},
            {"internalType": "uint256", "name": "balanceOnPool", "type": "uint256"},
            {"internalType": "uint256", "name": "totalBalance", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "_poolToken", "type": "address"},
            {"internalType": "address", "name": "_user", "type": "address"},
        ],
        "name": "getCurrentBorrowBalanceInOf",
        "outputs": [
            {"internalType": "uint256", "name": "balanceInP2P", "type": "uint256"},
            {"internalType": "uint256", "name": "balanceOnPool", "type": "uint256"},
            {"internalType": "uint256", "name": "totalBalance", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "_user", "type": "address"}],
        "name": "getUserHealthFactor",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Common Morpho Blue market IDs (these are market-specific)
MORPHO_BLUE_MARKETS = {
    # WETH/USDC markets
    "WETH-USDC-86": "0xb323495f7e4148be5643a4ea4a8221eef163e4bccfdedc2a6f4696baacbc86cc",
    "WETH-USDC-91.5": "0x7dde86a1e94561d9690ec678db673c1a6396365f7d1d65e129c5fff0990ff758",
    # WSTETH/USDC markets
    "WSTETH-USDC-86": "0x37e7484f6b37e2a4a1c6dcef5e8e4a2faf6c4f6c0e78a4a1a1e58a3a8d4e0000",
}


class MorphoAdapter(ProtocolAdapter):
    """Adapter for Morpho Blue and Morpho Optimizers."""

    def __init__(self, web3: AsyncWeb3 | None = None, use_blue: bool = True):
        self._web3 = web3 or get_web3()
        self._use_blue = use_blue

        if use_blue:
            self._morpho = self._web3.eth.contract(
                address=AsyncWeb3.to_checksum_address(MORPHO_BLUE),
                abi=MORPHO_BLUE_ABI,
            )
        else:
            # Legacy Morpho Aave optimizer
            self._morpho = self._web3.eth.contract(
                address=AsyncWeb3.to_checksum_address(MORPHO_AAVE_V2),
                abi=MORPHO_AAVE_ABI,
            )

    @property
    def name(self) -> str:
        return "Morpho Blue" if self._use_blue else "Morpho Aave"

    @property
    def protocol_url(self) -> str:
        return "https://app.morpho.org"

    async def _get_blue_position(self, wallet_address: str) -> Position | None:
        """Get position from Morpho Blue."""
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)

            total_collateral_usd = 0.0
            total_debt_usd = 0.0
            min_health_factor = float("inf")
            max_lltv = 0.0

            # Check known markets
            for market_name, market_id in MORPHO_BLUE_MARKETS.items():
                try:
                    # Get market params
                    market_params = await self._morpho.functions.idToMarketParams(
                        bytes.fromhex(market_id[2:])
                    ).call()
                    lltv = market_params[4] / 1e18  # Liquidation LTV

                    # Get user position
                    position = await self._morpho.functions.position(
                        bytes.fromhex(market_id[2:]),
                        checksum_address,
                    ).call()

                    supply_shares = position[0]
                    borrow_shares = position[1]
                    collateral = position[2]

                    if collateral == 0 and borrow_shares == 0:
                        continue

                    # Get market data to convert shares to assets
                    market_data = await self._morpho.functions.market(
                        bytes.fromhex(market_id[2:])
                    ).call()

                    total_supply_assets = market_data[0]
                    total_supply_shares = market_data[1]
                    total_borrow_assets = market_data[2]
                    total_borrow_shares = market_data[3]

                    # Convert shares to assets
                    if total_borrow_shares > 0:
                        borrow_assets = (borrow_shares * total_borrow_assets) // total_borrow_shares
                    else:
                        borrow_assets = 0

                    # Note: Need price oracle for accurate USD values
                    # Using placeholder for now
                    collateral_value = collateral / 1e18 * 1.0  # Placeholder price
                    debt_value = borrow_assets / 1e6  # Assuming USDC (6 decimals)

                    total_collateral_usd += collateral_value
                    total_debt_usd += debt_value

                    # Calculate health factor for this market
                    # HF = (collateral * lltv) / debt
                    if debt_value > 0:
                        hf = (collateral_value * lltv) / debt_value
                        min_health_factor = min(min_health_factor, hf)
                        max_lltv = max(max_lltv, lltv)

                except Exception:
                    continue

            if total_collateral_usd == 0 and total_debt_usd == 0:
                return None

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=min_health_factor if min_health_factor != float("inf") else float("inf"),
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                liquidation_threshold=max_lltv if max_lltv > 0 else 0.86,
                available_borrows_usd=0.0,
            )
        except Exception:
            return None

    async def _get_aave_optimizer_position(self, wallet_address: str) -> Position | None:
        """Get position from Morpho Aave V2 Optimizer (legacy)."""
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)

            # Get health factor directly from Morpho Aave
            health_factor = await self._morpho.functions.getUserHealthFactor(
                checksum_address
            ).call()

            health_factor = health_factor / 1e18 if health_factor < 2**255 else float("inf")

            if health_factor == 0:
                return None

            # Note: Would need to iterate through markets to get full position data
            # Simplified for now
            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=0.0,  # Would need additional calls
                total_debt_usd=0.0,
                liquidation_threshold=0.8,  # Approximate
                available_borrows_usd=0.0,
            )
        except Exception:
            return None

    async def get_position(self, wallet_address: str) -> Position | None:
        if self._use_blue:
            return await self._get_blue_position(wallet_address)
        else:
            return await self._get_aave_optimizer_position(wallet_address)

    async def get_health_factor(self, wallet_address: str) -> float | None:
        position = await self.get_position(wallet_address)
        return position.health_factor if position else None

    async def get_liquidation_threshold(self, wallet_address: str) -> float | None:
        position = await self.get_position(wallet_address)
        return position.liquidation_threshold if position else None

    async def has_position(self, wallet_address: str) -> bool:
        position = await self.get_position(wallet_address)
        return position is not None and position.health_factor != float("inf")


class MorphoAaveAdapter(MorphoAdapter):
    """Convenience class for Morpho Aave V2 Optimizer."""

    def __init__(self, web3: AsyncWeb3 | None = None):
        super().__init__(web3=web3, use_blue=False)

    @property
    def name(self) -> str:
        return "Morpho Aave V2"


class MorphoBlueAdapter(MorphoAdapter):
    """Convenience class for Morpho Blue."""

    def __init__(self, web3: AsyncWeb3 | None = None):
        super().__init__(web3=web3, use_blue=True)

    @property
    def name(self) -> str:
        return "Morpho Blue"
