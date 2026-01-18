from typing import List
from web3 import AsyncWeb3

from app.protocols.base import ProtocolAdapter, Position, Asset
from app.services.rpc import get_web3

# MakerDAO Core Contracts on Ethereum Mainnet
MAKER_CDP_MANAGER = "0x5ef30b9986345249bc32d8928B7ee64DE9435E39"
MAKER_VAT = "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B"
MAKER_SPOT = "0x65C79fcB50Ca1594B025960e539eD7A9a6D434A3"
MAKER_JUG = "0x19c0976f590D67707E62397C87829d896Dc0f1F1"
MAKER_ILK_REGISTRY = "0x5a464C28D19848f44199D003BeF5ecc87d090F87"

# Common ilk (collateral type) identifiers
ILKS = {
    "ETH-A": "0x4554482d41000000000000000000000000000000000000000000000000000000",
    "ETH-B": "0x4554482d42000000000000000000000000000000000000000000000000000000",
    "ETH-C": "0x4554482d43000000000000000000000000000000000000000000000000000000",
    "WBTC-A": "0x574254432d410000000000000000000000000000000000000000000000000000",
    "WBTC-B": "0x574254432d420000000000000000000000000000000000000000000000000000",
    "WBTC-C": "0x574254432d430000000000000000000000000000000000000000000000000000",
    "WSTETH-A": "0x5753544554482d41000000000000000000000000000000000000000000000000",
    "WSTETH-B": "0x5753544554482d42000000000000000000000000000000000000000000000000",
    "USDC-A": "0x555344432d410000000000000000000000000000000000000000000000000000",
}

CDP_MANAGER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "first",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "last",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "count",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "urns",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "ilks",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "list",
        "outputs": [
            {"internalType": "uint256", "name": "prev", "type": "uint256"},
            {"internalType": "uint256", "name": "next", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

VAT_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "", "type": "bytes32"},
            {"internalType": "address", "name": "", "type": "address"},
        ],
        "name": "urns",
        "outputs": [
            {"internalType": "uint256", "name": "ink", "type": "uint256"},
            {"internalType": "uint256", "name": "art", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"internalType": "uint256", "name": "Art", "type": "uint256"},
            {"internalType": "uint256", "name": "rate", "type": "uint256"},
            {"internalType": "uint256", "name": "spot", "type": "uint256"},
            {"internalType": "uint256", "name": "line", "type": "uint256"},
            {"internalType": "uint256", "name": "dust", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

SPOT_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"internalType": "contract PipLike", "name": "pip", "type": "address"},
            {"internalType": "uint256", "name": "mat", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

JUG_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"internalType": "uint256", "name": "duty", "type": "uint256"},
            {"internalType": "uint256", "name": "rho", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "base",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class MakerDAOAdapter(ProtocolAdapter):
    def __init__(self, web3: AsyncWeb3 | None = None):
        self._web3 = web3 or get_web3()
        self._cdp_manager = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(MAKER_CDP_MANAGER),
            abi=CDP_MANAGER_ABI,
        )
        self._vat = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(MAKER_VAT),
            abi=VAT_ABI,
        )
        self._spot = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(MAKER_SPOT),
            abi=SPOT_ABI,
        )
        self._jug = self._web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(MAKER_JUG),
            abi=JUG_ABI,
        )

    @property
    def name(self) -> str:
        return "MakerDAO"

    @property
    def protocol_url(self) -> str:
        return "https://summer.fi"

    async def _get_vault_ids(self, wallet_address: str) -> List[int]:
        """Get all vault IDs owned by an address."""
        try:
            checksum_address = AsyncWeb3.to_checksum_address(wallet_address)
            count = await self._cdp_manager.functions.count(checksum_address).call()

            if count == 0:
                return []

            vault_ids = []
            current = await self._cdp_manager.functions.first(checksum_address).call()

            while current != 0 and len(vault_ids) < count:
                vault_ids.append(current)
                list_data = await self._cdp_manager.functions.list(current).call()
                current = list_data[1]  # next

            return vault_ids
        except Exception:
            return []

    async def _get_vault_data(self, vault_id: int) -> dict | None:
        """Get vault data including collateral, debt, and collateralization ratio."""
        try:
            # Get urn address and ilk
            urn = await self._cdp_manager.functions.urns(vault_id).call()
            ilk = await self._cdp_manager.functions.ilks(vault_id).call()

            # Get vault position from VAT
            urn_data = await self._vat.functions.urns(ilk, urn).call()
            ink = urn_data[0]  # Collateral (in WAD - 18 decimals)
            art = urn_data[1]  # Normalized debt (in WAD)

            # Get ilk data from VAT
            ilk_data = await self._vat.functions.ilks(ilk).call()
            rate = ilk_data[1]  # Accumulated rate (RAY - 27 decimals)
            spot = ilk_data[2]  # Price with safety margin (RAY)

            # Get liquidation ratio from Spot
            spot_ilk = await self._spot.functions.ilks(ilk).call()
            mat = spot_ilk[1]  # Liquidation ratio (RAY) - e.g., 1.5e27 for 150%

            # Calculate actual debt (art * rate)
            debt_rad = art * rate  # RAD = 45 decimals
            debt_dai = debt_rad / 1e45  # Convert to DAI

            # Calculate collateral value
            # spot = price / mat, so price = spot * mat
            collateral_value = (ink * spot * mat) / (1e45 * 1e27)  # In DAI

            # Calculate collateralization ratio (Maker's health factor equivalent)
            # CR = (collateral * price) / debt = (ink * spot * mat) / (art * rate)
            if art > 0 and debt_dai > 0:
                collateralization_ratio = collateral_value / debt_dai
            else:
                collateralization_ratio = float("inf")

            # Liquidation threshold (inverse of mat)
            # If mat = 1.5, position is liquidated when CR < 150%, threshold = 1/1.5 = 0.667
            liquidation_threshold = 1e27 / mat if mat > 0 else 0

            # Convert ilk bytes32 to string for display
            ilk_name = ilk.rstrip(b'\x00').decode('utf-8', errors='ignore')

            return {
                "vault_id": vault_id,
                "ilk": ilk_name,
                "collateral": ink / 1e18,
                "debt": debt_dai,
                "collateral_value_usd": collateral_value,  # Approximation in DAI
                "collateralization_ratio": collateralization_ratio,
                "liquidation_threshold": liquidation_threshold,
                "mat": mat / 1e27,  # Human readable liquidation ratio (e.g., 1.5)
            }
        except Exception:
            return None

    async def get_position(self, wallet_address: str) -> Position | None:
        try:
            vault_ids = await self._get_vault_ids(wallet_address)

            if not vault_ids:
                return None

            total_collateral_usd = 0.0
            total_debt_usd = 0.0
            min_cr = float("inf")  # Track minimum collateralization ratio
            avg_liquidation_threshold = 0.0
            collateral_assets: List[Asset] = []
            debt_assets: List[Asset] = []

            for vault_id in vault_ids:
                vault_data = await self._get_vault_data(vault_id)
                if vault_data and vault_data["debt"] > 0:
                    total_collateral_usd += vault_data["collateral_value_usd"]
                    total_debt_usd += vault_data["debt"]
                    min_cr = min(min_cr, vault_data["collateralization_ratio"])
                    avg_liquidation_threshold = max(
                        avg_liquidation_threshold,
                        vault_data["liquidation_threshold"],
                    )

            if total_collateral_usd == 0 and total_debt_usd == 0:
                return None

            # Convert collateralization ratio to health factor
            # In Maker, CR of 150% (1.5) is the minimum for ETH-A
            # We normalize: HF = CR / mat (liquidation ratio)
            # So if CR = 1.5 and mat = 1.5, HF = 1.0 (at liquidation)
            # If CR = 2.0 and mat = 1.5, HF = 1.33 (safe)
            health_factor = min_cr if min_cr != float("inf") else float("inf")

            return Position(
                protocol=self.name,
                wallet_address=wallet_address,
                health_factor=health_factor,
                collateral_assets=collateral_assets,
                debt_assets=debt_assets,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                liquidation_threshold=avg_liquidation_threshold,
                available_borrows_usd=0.0,  # Complex calculation for Maker
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
        vault_ids = await self._get_vault_ids(wallet_address)
        return len(vault_ids) > 0

    async def get_vault_count(self, wallet_address: str) -> int:
        """Get the number of vaults owned by an address."""
        vault_ids = await self._get_vault_ids(wallet_address)
        return len(vault_ids)
