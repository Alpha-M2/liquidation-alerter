import logging
import math
from typing import List

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.protocols.base import ProtocolAdapter, Position, CollateralAsset, DebtAsset
from app.config import get_settings
from app.services.token_metadata import get_token_metadata_service

logger = logging.getLogger(__name__)

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
    # Extended methods for detailed position
    {
        "inputs": [],
        "name": "baseToken",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "utilization", "type": "uint256"}],
        "name": "getSupplyRate",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "utilization", "type": "uint256"}],
        "name": "getBorrowRate",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getUtilization",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseScale",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class CompoundV3Adapter(ProtocolAdapter):
    # Seconds per year for APY calculation
    SECONDS_PER_YEAR = 31536000

    def __init__(self, chain: str = "ethereum", web3: AsyncWeb3 | None = None, comet_address: str | None = None):
        self._chain = chain.lower()
        if self._chain not in COMPOUND_V3_COMET_ADDRESSES:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(COMPOUND_V3_COMET_ADDRESSES.keys())}")

        settings = get_settings()

        # Get chain-specific RPC URL from settings
        rpc_url = settings.get_rpc_url(self._chain)

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

    def _rate_to_apy(self, rate_per_second: int) -> float:
        """Convert per-second rate to APY.

        Compound V3 rates are per-second in 18 decimals.
        APY = ((1 + rate_per_second)^seconds_per_year) - 1
        """
        rate = rate_per_second / 1e18
        if rate <= 0:
            return 0.0
        # Use log/exp for large exponents to avoid overflow
        try:
            apy = math.exp(rate * self.SECONDS_PER_YEAR) - 1
        except OverflowError:
            apy = rate * self.SECONDS_PER_YEAR  # Linear approximation for very high rates
        return apy

    async def get_position(self, wallet_address: str) -> Position | None:
        """Get basic position data (backward compatible)."""
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
                chain=self._chain,
            )
        except Exception:
            return None

    async def get_detailed_position(self, wallet_address: str) -> Position | None:
        """Get detailed Compound V3 position with per-asset breakdown.

        Fetches granular data including:
        - Per-asset collateral balances, LTV, liquidation thresholds
        - Base token debt balance and APY
        - Supply APY for base token
        """
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            token_service = get_token_metadata_service()

            # Get base token info (e.g., USDC)
            base_token_address = await self._comet_contract.functions.baseToken().call()
            base_token_meta = await token_service.get_metadata(
                base_token_address, self._chain, self._web3
            )
            base_scale = await self._comet_contract.functions.baseScale().call()
            base_decimals = int(math.log10(base_scale)) if base_scale > 1 else 6

            # Get utilization and rates
            utilization = await self._comet_contract.functions.getUtilization().call()
            supply_rate_per_sec = await self._comet_contract.functions.getSupplyRate(utilization).call()
            borrow_rate_per_sec = await self._comet_contract.functions.getBorrowRate(utilization).call()

            # Convert per-second rate to APY
            supply_apy = self._rate_to_apy(supply_rate_per_sec)
            borrow_apy = self._rate_to_apy(borrow_rate_per_sec)

            # Get user's base token supply and borrow
            supply_balance = await self._comet_contract.functions.balanceOf(checksum_address).call()
            borrow_balance = await self._comet_contract.functions.borrowBalanceOf(checksum_address).call()

            # Get base token price
            base_price_feed = await self._comet_contract.functions.baseTokenPriceFeed().call()
            base_price = await self._comet_contract.functions.getPrice(base_price_feed).call()
            base_price_usd = base_price / 1e8  # Price feeds use 8 decimals

            # Build collateral assets list
            collateral_assets: List[CollateralAsset] = []
            num_assets = await self._comet_contract.functions.numAssets().call()
            total_collateral_usd = 0.0

            for i in range(num_assets):
                asset_info = await self._comet_contract.functions.getAssetInfo(i).call()
                asset_address = asset_info[1]
                price_feed = asset_info[2]
                scale = asset_info[3]  # 10^decimals
                borrow_collateral_factor = asset_info[4] / 1e18
                liquidate_collateral_factor = asset_info[5] / 1e18

                # Get user's collateral balance for this asset
                collateral_balance = await self._comet_contract.functions.collateralBalanceOf(
                    checksum_address, asset_address
                ).call()

                if collateral_balance > 0:
                    # Get token metadata
                    token_meta = await token_service.get_metadata(
                        asset_address, self._chain, self._web3
                    )

                    # Get price
                    price = await self._comet_contract.functions.getPrice(price_feed).call()
                    price_usd = price / 1e8

                    # Calculate values
                    decimals = int(math.log10(scale)) if scale > 1 else 18
                    balance_tokens = collateral_balance / scale
                    balance_usd = balance_tokens * price_usd

                    collateral_asset = CollateralAsset(
                        symbol=token_meta.symbol if token_meta else f"ASSET_{i}",
                        address=asset_address,
                        balance=balance_tokens,
                        balance_usd=balance_usd,
                        price_usd=price_usd,
                        decimals=decimals,
                        is_collateral_enabled=True,  # Always true if has balance
                        ltv=borrow_collateral_factor,
                        liquidation_threshold=liquidate_collateral_factor,
                        supply_apy=None,  # Collateral doesn't earn supply APY in Compound V3
                    )

                    collateral_assets.append(collateral_asset)
                    total_collateral_usd += balance_usd

            # Build debt assets list
            debt_assets: List[DebtAsset] = []
            total_debt_usd = 0.0

            if borrow_balance > 0:
                borrow_tokens = borrow_balance / base_scale
                borrow_usd = borrow_tokens * base_price_usd

                debt_asset = DebtAsset(
                    symbol=base_token_meta.symbol if base_token_meta else "USDC",
                    address=base_token_address,
                    balance=borrow_tokens,
                    balance_usd=borrow_usd,
                    price_usd=base_price_usd,
                    decimals=base_decimals,
                    interest_rate_mode="variable",
                    borrow_apy=borrow_apy,
                )

                debt_assets.append(debt_asset)
                total_debt_usd = borrow_usd

            # Add supply as "collateral" (base token supply earns interest)
            if supply_balance > 0:
                supply_tokens = supply_balance / base_scale
                supply_usd = supply_tokens * base_price_usd

                # Note: In Compound V3, base token supply can't be used as collateral
                # But we show it as a collateral-like asset for completeness
                supply_asset = CollateralAsset(
                    symbol=base_token_meta.symbol if base_token_meta else "USDC",
                    address=base_token_address,
                    balance=supply_tokens,
                    balance_usd=supply_usd,
                    price_usd=base_price_usd,
                    decimals=base_decimals,
                    is_collateral_enabled=False,  # Base token supply is NOT collateral
                    ltv=0.0,
                    liquidation_threshold=0.0,
                    supply_apy=supply_apy,
                )

                collateral_assets.insert(0, supply_asset)  # Show first
                total_collateral_usd += supply_usd

            if not collateral_assets and not debt_assets:
                return None

            # Calculate health factor
            if total_debt_usd > 0:
                # Use weighted liquidation factor from actual collateral (not base supply)
                actual_collateral = [a for a in collateral_assets if a.is_collateral_enabled]
                if actual_collateral:
                    weighted_liq_threshold = sum(
                        a.liquidation_threshold * a.balance_usd
                        for a in actual_collateral
                    ) / sum(a.balance_usd for a in actual_collateral)

                    collateral_for_hf = sum(a.balance_usd for a in actual_collateral)
                    health_factor = (collateral_for_hf * weighted_liq_threshold) / total_debt_usd
                else:
                    weighted_liq_threshold = 0.8
                    health_factor = 0.0  # No collateral but has debt
            else:
                health_factor = float("inf")
                weighted_liq_threshold = 0.8  # Default

            # Calculate available borrows
            actual_collateral = [a for a in collateral_assets if a.is_collateral_enabled]
            if actual_collateral:
                max_borrow = sum(a.balance_usd * a.ltv for a in actual_collateral)
                available_borrows = max(0, max_borrow - total_debt_usd)
            else:
                available_borrows = 0.0

            # Calculate net APY
            net_apy = None
            if total_collateral_usd > 0:
                supply_earnings = sum(
                    a.balance_usd * (a.supply_apy or 0)
                    for a in collateral_assets
                )
                borrow_costs = total_debt_usd * borrow_apy
                net_apy = (supply_earnings - borrow_costs) / total_collateral_usd

            return Position(
                protocol=self.name,
                chain=self._chain,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=collateral_assets,
                debt_assets=debt_assets,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                liquidation_threshold=weighted_liq_threshold,
                available_borrows_usd=available_borrows,
                net_apy=net_apy,
            )

        except Exception as e:
            logger.error(f"Error fetching detailed Compound V3 position for {wallet_address}: {e}")
            return await self.get_position(wallet_address)

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
