from typing import List
from web3 import AsyncWeb3

from app.protocols.base import ProtocolAdapter, Position, Asset
from app.services.rpc import get_web3

# Compound V2 Comptroller on Ethereum Mainnet
COMPOUND_V2_COMPTROLLER = "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B"

# Common cToken addresses
CTOKENS = {
    "cETH": "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5",
    "cUSDC": "0x39AA39c021dfbaE8faC545936693aC917d5E7563",
    "cDAI": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
    "cUSDT": "0xf650C3d88D12dB855b8bf7D11Be6C55A4e07dCC9",
    "cWBTC": "0xccF4429DB6322D5C611ee964527D42E5d685DD6a",
    "cLINK": "0xFAce851a4921ce59e912d19329929CE6da6EB0c7",
    "cUNI": "0x35A18000230DA775CAc24873d00Ff85BccdeD550",
    "cCOMP": "0x70e36f6BF80a52b3B46b3aF8e106CC0ed743E8e4",
}

COMPTROLLER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "getAccountLiquidity",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "getAssetsIn",
        "outputs": [{"internalType": "contract CToken[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "markets",
        "outputs": [
            {"internalType": "bool", "name": "isListed", "type": "bool"},
            {"internalType": "uint256", "name": "collateralFactorMantissa", "type": "uint256"},
            {"internalType": "bool", "name": "isComped", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

CTOKEN_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "getAccountSnapshot",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "borrowBalanceStored",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "exchangeRateStored",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "underlying",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowRatePerBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyRatePerBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class CompoundV2Adapter(ProtocolAdapter):
    def __init__(self, web3: AsyncWeb3 | None = None):
        self._web3 = web3 or get_web3()
        self._comptroller = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(COMPOUND_V2_COMPTROLLER),
            abi=COMPTROLLER_ABI,
        )

    @property
    def name(self) -> str:
        return "Compound V2"

    @property
    def protocol_url(self) -> str:
        return "https://app.compound.finance"

    async def get_position(self, wallet_address: str) -> Position | None:
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)

            # Get account liquidity (error, liquidity, shortfall)
            liquidity_data = await self._comptroller.functions.getAccountLiquidity(
                checksum_address
            ).call()

            error = liquidity_data[0]
            liquidity = liquidity_data[1] / 1e18  # Excess liquidity in USD
            shortfall = liquidity_data[2] / 1e18  # Shortfall in USD (if undercollateralized)

            if error != 0:
                return None

            # Get markets the user has entered
            markets = await self._comptroller.functions.getAssetsIn(checksum_address).call()

            if not markets:
                return None

            total_collateral_usd = 0.0
            total_debt_usd = 0.0
            collateral_assets: List[Asset] = []
            debt_assets: List[Asset] = []
            weighted_collateral_factor = 0.0

            for market_address in markets:
                ctoken = self._web3.eth.contract(
                    address=market_address,
                    abi=CTOKEN_ABI,
                )

                # Get account snapshot: (error, cTokenBalance, borrowBalance, exchangeRateMantissa)
                snapshot = await ctoken.functions.getAccountSnapshot(checksum_address).call()

                if snapshot[0] != 0:  # Error
                    continue

                ctoken_balance = snapshot[1]
                borrow_balance = snapshot[2]
                exchange_rate = snapshot[3] / 1e18

                # Get collateral factor for this market
                market_info = await self._comptroller.functions.markets(market_address).call()
                collateral_factor = market_info[1] / 1e18

                # Calculate underlying balance
                underlying_balance = (ctoken_balance * exchange_rate) / 1e18

                # Note: For accurate USD values, we need price oracle
                # This will be enhanced with Chainlink integration
                # For now, using placeholder values
                price_usd = 1.0  # Placeholder

                if underlying_balance > 0:
                    collateral_value = underlying_balance * price_usd
                    total_collateral_usd += collateral_value
                    weighted_collateral_factor += collateral_value * collateral_factor

                if borrow_balance > 0:
                    debt_value = (borrow_balance / 1e18) * price_usd
                    total_debt_usd += debt_value

            if total_collateral_usd == 0 and total_debt_usd == 0:
                return None

            # Calculate health factor for Compound V2
            # Compound uses "shortfall" concept - if shortfall > 0, position is liquidatable
            # We convert to health factor: HF = (collateral * avg_collateral_factor) / debt
            avg_collateral_factor = (
                weighted_collateral_factor / total_collateral_usd
                if total_collateral_usd > 0
                else 0.75
            )

            if total_debt_usd > 0:
                health_factor = (total_collateral_usd * avg_collateral_factor) / total_debt_usd
            else:
                health_factor = float("inf")

            # If there's a shortfall, the position is underwater
            if shortfall > 0:
                health_factor = min(health_factor, 0.99)

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=collateral_assets,
                debt_assets=debt_assets,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                liquidation_threshold=avg_collateral_factor,
                available_borrows_usd=liquidity,
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

    async def get_shortfall(self, wallet_address: str) -> float:
        """Get the shortfall amount (Compound-specific). Returns > 0 if liquidatable."""
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            liquidity_data = await self._comptroller.functions.getAccountLiquidity(
                checksum_address
            ).call()
            return liquidity_data[2] / 1e18
        except Exception:
            return 0.0
