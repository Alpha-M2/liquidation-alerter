"""Aave V3 protocol adapter for multi-chain position monitoring.

This module implements the ProtocolAdapter interface for Aave V3, supporting
Ethereum, Arbitrum, Base, and Optimism. It fetches position data including
per-asset collateral and debt breakdowns with APYs using the UiPoolDataProvider.
"""

import logging
from typing import Dict, List, Any

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.protocols.base import ProtocolAdapter, Position, CollateralAsset, DebtAsset
from app.config import get_settings
from app.services.cache import get_position_cache

logger = logging.getLogger(__name__)

# Aave V3 Pool addresses per chain
AAVE_V3_POOL_ADDRESSES = {
    "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    "base": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
    "optimism": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
}

# Aave V3 Pool Addresses Provider (needed for UiPoolDataProvider calls)
AAVE_V3_POOL_ADDRESSES_PROVIDER = {
    "ethereum": "0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e",
    "arbitrum": "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb",
    "base": "0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D",
    "optimism": "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb",
}

# UiPoolDataProviderV3 addresses per chain
AAVE_V3_UI_POOL_DATA_PROVIDER = {
    "ethereum": "0x91c0eA31b49B69Ea18607702c61A09E4Be91B8FE",
    "arbitrum": "0x145dE30c929a065582da84Cf96F88460dB9745A7",
    "base": "0x174446a6741300cD2E7C1b1A636Fee99c8F83502",
    "optimism": "0xbd83DdBE37fc91923d59C8c1E0bDe0CccC332C6f",
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

# UiPoolDataProviderV3 ABI (only the methods we need)
UI_POOL_DATA_PROVIDER_ABI = [
    {
        "inputs": [
            {"internalType": "contract IPoolAddressesProvider", "name": "provider", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"}
        ],
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
                "internalType": "struct IUiPoolDataProviderV3.UserReserveData[]",
                "name": "",
                "type": "tuple[]"
            },
            {"internalType": "uint8", "name": "", "type": "uint8"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "contract IPoolAddressesProvider", "name": "provider", "type": "address"}
        ],
        "name": "getReservesData",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "underlyingAsset", "type": "address"},
                    {"internalType": "string", "name": "name", "type": "string"},
                    {"internalType": "string", "name": "symbol", "type": "string"},
                    {"internalType": "uint256", "name": "decimals", "type": "uint256"},
                    {"internalType": "uint256", "name": "baseLTVasCollateral", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveLiquidationThreshold", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveLiquidationBonus", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveFactor", "type": "uint256"},
                    {"internalType": "bool", "name": "usageAsCollateralEnabled", "type": "bool"},
                    {"internalType": "bool", "name": "borrowingEnabled", "type": "bool"},
                    {"internalType": "bool", "name": "stableBorrowRateEnabled", "type": "bool"},
                    {"internalType": "bool", "name": "isActive", "type": "bool"},
                    {"internalType": "bool", "name": "isFrozen", "type": "bool"},
                    {"internalType": "uint128", "name": "liquidityIndex", "type": "uint128"},
                    {"internalType": "uint128", "name": "variableBorrowIndex", "type": "uint128"},
                    {"internalType": "uint128", "name": "liquidityRate", "type": "uint128"},
                    {"internalType": "uint128", "name": "variableBorrowRate", "type": "uint128"},
                    {"internalType": "uint128", "name": "stableBorrowRate", "type": "uint128"},
                    {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"},
                    {"internalType": "address", "name": "aTokenAddress", "type": "address"},
                    {"internalType": "address", "name": "stableDebtTokenAddress", "type": "address"},
                    {"internalType": "address", "name": "variableDebtTokenAddress", "type": "address"},
                    {"internalType": "address", "name": "interestRateStrategyAddress", "type": "address"},
                    {"internalType": "uint256", "name": "availableLiquidity", "type": "uint256"},
                    {"internalType": "uint256", "name": "totalPrincipalStableDebt", "type": "uint256"},
                    {"internalType": "uint256", "name": "averageStableRate", "type": "uint256"},
                    {"internalType": "uint256", "name": "stableDebtLastUpdateTimestamp", "type": "uint256"},
                    {"internalType": "uint256", "name": "totalScaledVariableDebt", "type": "uint256"},
                    {"internalType": "uint256", "name": "priceInMarketReferenceCurrency", "type": "uint256"},
                    {"internalType": "uint256", "name": "priceOracle", "type": "uint256"},
                    {"internalType": "uint256", "name": "variableRateSlope1", "type": "uint256"},
                    {"internalType": "uint256", "name": "variableRateSlope2", "type": "uint256"},
                    {"internalType": "uint256", "name": "stableRateSlope1", "type": "uint256"},
                    {"internalType": "uint256", "name": "stableRateSlope2", "type": "uint256"},
                    {"internalType": "uint256", "name": "baseStableBorrowRate", "type": "uint256"},
                    {"internalType": "uint256", "name": "baseVariableBorrowRate", "type": "uint256"},
                    {"internalType": "uint256", "name": "optimalUsageRatio", "type": "uint256"},
                    {"internalType": "bool", "name": "isPaused", "type": "bool"},
                    {"internalType": "bool", "name": "isSiloedBorrowing", "type": "bool"},
                    {"internalType": "uint128", "name": "accruedToTreasury", "type": "uint128"},
                    {"internalType": "uint128", "name": "unbacked", "type": "uint128"},
                    {"internalType": "uint128", "name": "isolationModeTotalDebt", "type": "uint128"},
                    {"internalType": "bool", "name": "flashLoanEnabled", "type": "bool"},
                    {"internalType": "uint256", "name": "debtCeiling", "type": "uint256"},
                    {"internalType": "uint256", "name": "debtCeilingDecimals", "type": "uint256"},
                    {"internalType": "uint8", "name": "eModeCategoryId", "type": "uint8"},
                    {"internalType": "uint256", "name": "borrowCap", "type": "uint256"},
                    {"internalType": "uint256", "name": "supplyCap", "type": "uint256"},
                    {"internalType": "uint16", "name": "eModeLtv", "type": "uint16"},
                    {"internalType": "uint16", "name": "eModeLiquidationThreshold", "type": "uint16"},
                    {"internalType": "uint16", "name": "eModeLiquidationBonus", "type": "uint16"},
                    {"internalType": "address", "name": "eModePriceSource", "type": "address"},
                    {"internalType": "string", "name": "eModeLabel", "type": "string"},
                    {"internalType": "bool", "name": "borrowableInIsolation", "type": "bool"}
                ],
                "internalType": "struct IUiPoolDataProviderV3.AggregatedReserveData[]",
                "name": "",
                "type": "tuple[]"
            },
            {
                "components": [
                    {"internalType": "uint256", "name": "marketReferenceCurrencyUnit", "type": "uint256"},
                    {"internalType": "int256", "name": "marketReferenceCurrencyPriceInUsd", "type": "int256"},
                    {"internalType": "int256", "name": "networkBaseTokenPriceInUsd", "type": "int256"},
                    {"internalType": "uint8", "name": "networkBaseTokenPriceDecimals", "type": "uint8"}
                ],
                "internalType": "struct IUiPoolDataProviderV3.BaseCurrencyInfo",
                "name": "",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]


class AaveV3Adapter(ProtocolAdapter):
    def __init__(self, chain: str = "ethereum", web3: AsyncWeb3 | None = None):
        self._chain = chain.lower()
        if self._chain not in AAVE_V3_POOL_ADDRESSES:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(AAVE_V3_POOL_ADDRESSES.keys())}")

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

        pool_address = AAVE_V3_POOL_ADDRESSES[self._chain]
        self._pool_contract = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(pool_address),
            abi=POOL_ABI,
        )

        # Initialize UiPoolDataProvider contract
        if self._chain in AAVE_V3_UI_POOL_DATA_PROVIDER:
            ui_provider_address = AAVE_V3_UI_POOL_DATA_PROVIDER[self._chain]
            self._ui_data_provider = self._web3.eth.contract(
                address=AsyncWeb3.to_checksum_address(ui_provider_address),
                abi=UI_POOL_DATA_PROVIDER_ABI,
            )
        else:
            self._ui_data_provider = None

        self._position_cache = get_position_cache()

    @property
    def name(self) -> str:
        chain_display = self._chain.capitalize()
        return f"Aave V3 ({chain_display})"

    @property
    def chain(self) -> str:
        return self._chain

    def _ray_to_percent(self, ray_value: int) -> float:
        """Convert ray (1e27) to decimal (e.g., 0.032 for 3.2% APY)."""
        return ray_value / 1e27

    def _calculate_actual_balance(
        self,
        scaled_balance: int,
        index: int,
        decimals: int,
    ) -> float:
        """Convert scaled balance to actual token amount using liquidity/borrow index.

        Args:
            scaled_balance: Scaled balance from Aave (aToken or variable debt)
            index: Liquidity index (for supply) or variable borrow index (for debt)
            decimals: Token decimals

        Returns:
            Actual token balance as float
        """
        if scaled_balance == 0 or index == 0:
            return 0.0
        # actual = scaled_balance * index / 1e27
        actual_raw = (scaled_balance * index) // (10**27)
        return actual_raw / (10**decimals)

    def _build_reserve_map(
        self,
        reserves_data: List[Any],
        base_currency_info: Any,
    ) -> Dict[str, Dict]:
        """Build a map of asset_address -> reserve info for quick lookup.

        Args:
            reserves_data: List of reserve tuples from getReservesData
            base_currency_info: Base currency info tuple

        Returns:
            Dict mapping asset address -> reserve info dict
        """
        # Extract base currency pricing info
        market_ref_unit = base_currency_info[0]  # Usually 1e8 for USD
        market_ref_price_usd = base_currency_info[1]  # Price of reference currency in USD

        reserve_map = {}
        for reserve in reserves_data:
            asset_address = reserve[0]
            reserve_map[asset_address] = {
                "underlying_asset": asset_address,
                "name": reserve[1],
                "symbol": reserve[2],
                "decimals": int(reserve[3]),
                "ltv": reserve[4] / 1e4,  # Basis points to decimal
                "liquidation_threshold": reserve[5] / 1e4,
                "liquidation_bonus": reserve[6] / 1e4,
                "usage_as_collateral_enabled": reserve[8],
                "borrowing_enabled": reserve[9],
                "is_active": reserve[11],
                "liquidity_index": reserve[13],
                "variable_borrow_index": reserve[14],
                "liquidity_rate": reserve[15],  # Supply APY (ray)
                "variable_borrow_rate": reserve[16],  # Variable borrow APY (ray)
                "stable_borrow_rate": reserve[17],  # Stable borrow APY (ray)
                "price_in_market_ref": reserve[28],  # Price in market reference currency
                "market_ref_unit": market_ref_unit,
                "market_ref_price_usd": market_ref_price_usd,
            }

        return reserve_map

    def _calculate_price_usd(self, reserve_info: Dict) -> float:
        """Calculate USD price for a reserve asset.

        Args:
            reserve_info: Reserve info dict from _build_reserve_map

        Returns:
            Price in USD
        """
        price_in_market_ref = reserve_info["price_in_market_ref"]
        market_ref_price_usd = reserve_info["market_ref_price_usd"]
        market_ref_unit = reserve_info["market_ref_unit"]

        if market_ref_unit == 0:
            return 0.0

        # price_in_market_ref is in 8 decimals (like Chainlink)
        # market_ref_price_usd is also in 8 decimals
        # Result: price_usd = (price_in_market_ref * market_ref_price_usd) / (market_ref_unit * 1e8)
        # Since market_ref_unit is typically 1e8 and market_ref_price_usd is 1e8 (for USD):
        # Simplified: price_usd = price_in_market_ref / 1e8 when market_ref is USD

        # For ETH-based reference (mainnet): market_ref_price_usd converts ETH to USD
        if market_ref_price_usd > 0:
            price_usd = (price_in_market_ref * market_ref_price_usd) / (market_ref_unit * 1e8)
        else:
            # Fallback: assume price is already in USD
            price_usd = price_in_market_ref / 1e8

        return price_usd

    async def _process_collateral(
        self,
        user_reserve: Any,
        reserve_info: Dict,
    ) -> CollateralAsset | None:
        """Process user reserve data into CollateralAsset.

        Args:
            user_reserve: User reserve tuple from getUserReservesData
            reserve_info: Reserve info dict from _build_reserve_map

        Returns:
            CollateralAsset or None if no supply balance
        """
        scaled_atoken_balance = user_reserve[1]
        is_collateral_enabled = user_reserve[2]

        if scaled_atoken_balance == 0:
            return None

        decimals = reserve_info["decimals"]
        liquidity_index = reserve_info["liquidity_index"]

        # Calculate actual balance
        balance = self._calculate_actual_balance(
            scaled_atoken_balance,
            liquidity_index,
            decimals,
        )

        if balance <= 0:
            return None

        # Calculate USD value
        price_usd = self._calculate_price_usd(reserve_info)
        balance_usd = balance * price_usd

        # Get supply APY
        supply_apy = self._ray_to_percent(reserve_info["liquidity_rate"])

        return CollateralAsset(
            symbol=reserve_info["symbol"],
            address=reserve_info["underlying_asset"],
            balance=balance,
            balance_usd=balance_usd,
            price_usd=price_usd,
            decimals=decimals,
            is_collateral_enabled=is_collateral_enabled,
            ltv=reserve_info["ltv"],
            liquidation_threshold=reserve_info["liquidation_threshold"],
            supply_apy=supply_apy,
        )

    async def _process_debt(
        self,
        user_reserve: Any,
        reserve_info: Dict,
    ) -> List[DebtAsset]:
        """Process user reserve data into DebtAsset(s).

        Can return up to 2 debt assets (variable and stable) per reserve.

        Args:
            user_reserve: User reserve tuple from getUserReservesData
            reserve_info: Reserve info dict from _build_reserve_map

        Returns:
            List of DebtAsset objects (may be empty)
        """
        scaled_variable_debt = user_reserve[4]
        principal_stable_debt = user_reserve[5]

        debt_assets = []
        decimals = reserve_info["decimals"]
        price_usd = self._calculate_price_usd(reserve_info)

        # Process variable debt
        if scaled_variable_debt > 0:
            variable_borrow_index = reserve_info["variable_borrow_index"]
            variable_balance = self._calculate_actual_balance(
                scaled_variable_debt,
                variable_borrow_index,
                decimals,
            )

            if variable_balance > 0:
                variable_balance_usd = variable_balance * price_usd
                variable_borrow_apy = self._ray_to_percent(reserve_info["variable_borrow_rate"])

                debt_assets.append(DebtAsset(
                    symbol=reserve_info["symbol"],
                    address=reserve_info["underlying_asset"],
                    balance=variable_balance,
                    balance_usd=variable_balance_usd,
                    price_usd=price_usd,
                    decimals=decimals,
                    interest_rate_mode="variable",
                    borrow_apy=variable_borrow_apy,
                ))

        # Process stable debt (less common, Aave is deprecating stable rates)
        if principal_stable_debt > 0:
            # Stable debt doesn't use an index, it's the principal amount
            stable_balance = principal_stable_debt / (10**decimals)

            if stable_balance > 0:
                stable_balance_usd = stable_balance * price_usd
                stable_borrow_apy = self._ray_to_percent(reserve_info["stable_borrow_rate"])

                debt_assets.append(DebtAsset(
                    symbol=reserve_info["symbol"],
                    address=reserve_info["underlying_asset"],
                    balance=stable_balance,
                    balance_usd=stable_balance_usd,
                    price_usd=price_usd,
                    decimals=decimals,
                    interest_rate_mode="stable",
                    borrow_apy=stable_borrow_apy,
                    stable_borrow_apy=stable_borrow_apy,
                ))

        return debt_assets

    async def get_position(self, wallet_address: str) -> Position | None:
        """Get basic position data (backward compatible)."""
        # Check cache first
        cached = self._position_cache.get_basic(wallet_address, self.name)
        if cached is not None:
            return cached

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

            position = Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=[],
                debt_assets=[],
                total_collateral_usd=total_collateral_base,
                total_debt_usd=total_debt_base,
                liquidation_threshold=liquidation_threshold,
                available_borrows_usd=available_borrows_base,
                chain=self._chain,
            )
            self._position_cache.set_basic(wallet_address, self.name, position)
            return position
        except Exception:
            return None

    async def get_detailed_position(self, wallet_address: str) -> Position | None:
        """Get detailed position with per-asset breakdown.

        Fetches granular data including:
        - Per-asset collateral balances, LTV, liquidation thresholds
        - Per-asset debt balances, interest rate modes, APYs
        - Supply and borrow APYs

        Falls back to basic position if UI data provider is unavailable.
        """
        # Check cache first
        cached = self._position_cache.get_detailed(wallet_address, self.name)
        if cached is not None:
            return cached

        if not self._ui_data_provider:
            logger.debug(f"UI data provider not available for {self._chain}, using basic position")
            return await self.get_position(wallet_address)

        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            provider_address = AAVE_V3_POOL_ADDRESSES_PROVIDER[self._chain]

            # Fetch reserves data (symbols, prices, APYs, thresholds)
            reserves_data, base_currency_info = await self._ui_data_provider.functions.getReservesData(
                provider_address
            ).call()

            # Fetch user's reserves data (balances, collateral flags)
            user_reserves_data, _ = await self._ui_data_provider.functions.getUserReservesData(
                provider_address, checksum_address
            ).call()

            # Build lookup map: asset_address -> reserve_info
            reserve_map = self._build_reserve_map(reserves_data, base_currency_info)

            # Process user reserves into CollateralAsset and DebtAsset objects
            collateral_assets: List[CollateralAsset] = []
            debt_assets: List[DebtAsset] = []
            total_collateral_usd = 0.0
            total_debt_usd = 0.0
            total_supply_weighted_apy = 0.0
            total_borrow_weighted_apy = 0.0

            for user_reserve in user_reserves_data:
                asset_address = user_reserve[0]
                if asset_address not in reserve_map:
                    continue

                reserve_info = reserve_map[asset_address]

                # Process supply (collateral)
                collateral = await self._process_collateral(user_reserve, reserve_info)
                if collateral and collateral.balance > 0:
                    collateral_assets.append(collateral)
                    total_collateral_usd += collateral.balance_usd
                    if collateral.supply_apy:
                        total_supply_weighted_apy += collateral.balance_usd * collateral.supply_apy

                # Process debt
                debts = await self._process_debt(user_reserve, reserve_info)
                for debt in debts:
                    if debt.balance > 0:
                        debt_assets.append(debt)
                        total_debt_usd += debt.balance_usd
                        total_borrow_weighted_apy += debt.balance_usd * debt.borrow_apy

            # No position if no assets
            if not collateral_assets and not debt_assets:
                return None

            # Calculate weighted liquidation threshold
            if total_collateral_usd > 0:
                weighted_liq_threshold = sum(
                    a.liquidation_threshold * a.balance_usd
                    for a in collateral_assets if a.is_collateral_enabled
                ) / sum(
                    a.balance_usd
                    for a in collateral_assets if a.is_collateral_enabled
                ) if any(a.is_collateral_enabled for a in collateral_assets) else 0.8
            else:
                weighted_liq_threshold = 0.8

            # Calculate health factor
            if total_debt_usd > 0:
                collateral_for_hf = sum(
                    a.balance_usd * a.liquidation_threshold
                    for a in collateral_assets if a.is_collateral_enabled
                )
                health_factor = collateral_for_hf / total_debt_usd
            else:
                health_factor = float("inf")

            # Calculate available borrows
            if total_collateral_usd > 0 and any(a.is_collateral_enabled for a in collateral_assets):
                max_borrow = sum(
                    a.balance_usd * a.ltv
                    for a in collateral_assets if a.is_collateral_enabled
                )
                available_borrows = max(0, max_borrow - total_debt_usd)
            else:
                available_borrows = 0.0

            # Calculate net APY
            net_apy = None
            if total_collateral_usd > 0 or total_debt_usd > 0:
                supply_apy = total_supply_weighted_apy / total_collateral_usd if total_collateral_usd > 0 else 0
                borrow_apy = total_borrow_weighted_apy / total_debt_usd if total_debt_usd > 0 else 0
                # Net APY = (supply earnings - borrow costs) / total collateral
                if total_collateral_usd > 0:
                    supply_earnings = total_collateral_usd * supply_apy
                    borrow_costs = total_debt_usd * borrow_apy
                    net_apy = (supply_earnings - borrow_costs) / total_collateral_usd

            position = Position(
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
            self._position_cache.set_detailed(wallet_address, self.name, position)
            return position

        except Exception as e:
            logger.error(f"Error fetching detailed position for {wallet_address} on {self.name}: {e}")
            # Fallback to basic position
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
