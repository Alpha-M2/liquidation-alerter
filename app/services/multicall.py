"""
Multicall utility for batching multiple RPC calls into a single request.

Uses Multicall3 contract which is deployed at the same address on all major EVM chains.
This significantly reduces RPC call volume and improves performance.
"""

import logging
from dataclasses import dataclass
from typing import Any, List, Tuple

from web3 import AsyncWeb3
from eth_abi import decode, encode

logger = logging.getLogger(__name__)

# Multicall3 is deployed at the same address on all major EVM chains
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

MULTICALL3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "payable",
        "type": "function",
    }
]


@dataclass
class Call:
    """Represents a single contract call to be batched."""
    target: str  # Contract address
    call_data: bytes  # Encoded function call
    allow_failure: bool = True  # Whether to continue if this call fails


@dataclass
class CallResult:
    """Result of a single call within a multicall batch."""
    success: bool
    return_data: bytes


class MulticallService:
    """
    Service for batching multiple contract calls into a single RPC request.

    This dramatically reduces the number of RPC calls needed when monitoring
    multiple positions across multiple protocols.

    Example usage:
        multicall = MulticallService(web3)

        # Build calls
        calls = [
            multicall.build_call(
                aave_pool_address,
                "getUserAccountData(address)",
                ["address"],
                [wallet_address]
            )
            for wallet_address in wallets
        ]

        # Execute batch
        results = await multicall.execute(calls)
    """

    def __init__(self, web3: AsyncWeb3):
        self._web3 = web3
        self._multicall_contract = web3.eth.contract(
            address=AsyncWeb3.to_checksum_address(MULTICALL3_ADDRESS),
            abi=MULTICALL3_ABI,
        )

    def build_call(
        self,
        target: str,
        function_signature: str,
        input_types: List[str],
        input_values: List[Any],
        allow_failure: bool = True,
    ) -> Call:
        """
        Build a Call object for inclusion in a multicall batch.

        Args:
            target: Contract address to call
            function_signature: Function signature (e.g., "getUserAccountData(address)")
            input_types: List of input types (e.g., ["address"])
            input_values: List of input values
            allow_failure: Whether to continue if this call fails

        Returns:
            Call object ready for batching
        """
        # Get function selector (first 4 bytes of keccak256 hash)
        selector = self._web3.keccak(text=function_signature)[:4]

        # Encode the input parameters
        if input_types and input_values:
            encoded_params = encode(input_types, input_values)
            call_data = selector + encoded_params
        else:
            call_data = selector

        return Call(
            target=AsyncWeb3.to_checksum_address(target),
            call_data=call_data,
            allow_failure=allow_failure,
        )

    async def execute(self, calls: List[Call]) -> List[CallResult]:
        """
        Execute a batch of calls in a single RPC request.

        Args:
            calls: List of Call objects to execute

        Returns:
            List of CallResult objects with success status and return data
        """
        if not calls:
            return []

        # Format calls for Multicall3
        formatted_calls = [
            (call.target, call.allow_failure, call.call_data)
            for call in calls
        ]

        try:
            # Execute the multicall
            results = await self._multicall_contract.functions.aggregate3(
                formatted_calls
            ).call()

            return [
                CallResult(success=result[0], return_data=result[1])
                for result in results
            ]

        except Exception as e:
            logger.error(f"Multicall execution failed: {e}")
            # Return failures for all calls
            return [CallResult(success=False, return_data=b"") for _ in calls]

    @staticmethod
    def decode_result(
        result: CallResult,
        output_types: List[str],
    ) -> Tuple[bool, Any]:
        """
        Decode the return data from a call result.

        Args:
            result: CallResult from execute()
            output_types: List of output types to decode

        Returns:
            Tuple of (success, decoded_values)
        """
        if not result.success or not result.return_data:
            return False, None

        try:
            decoded = decode(output_types, result.return_data)
            return True, decoded
        except Exception as e:
            logger.error(f"Failed to decode multicall result: {e}")
            return False, None


class BatchPositionFetcher:
    """
    High-level utility for fetching multiple positions in batched calls.

    Optimized for fetching Aave V3 and Compound V3 positions.
    """

    # Aave V3 getUserAccountData output types
    AAVE_OUTPUT_TYPES = [
        "uint256",  # totalCollateralBase
        "uint256",  # totalDebtBase
        "uint256",  # availableBorrowsBase
        "uint256",  # currentLiquidationThreshold
        "uint256",  # ltv
        "uint256",  # healthFactor
    ]

    def __init__(self, web3: AsyncWeb3):
        self._multicall = MulticallService(web3)

    async def fetch_aave_positions(
        self,
        pool_address: str,
        wallet_addresses: List[str],
    ) -> List[Tuple[str, dict | None]]:
        """
        Fetch multiple Aave V3 positions in a single batched call.

        Args:
            pool_address: Aave V3 Pool contract address
            wallet_addresses: List of wallet addresses to check

        Returns:
            List of (wallet_address, position_data) tuples
        """
        if not wallet_addresses:
            return []

        # Build calls for all wallets
        calls = [
            self._multicall.build_call(
                target=pool_address,
                function_signature="getUserAccountData(address)",
                input_types=["address"],
                input_values=[AsyncWeb3.to_checksum_address(addr)],
            )
            for addr in wallet_addresses
        ]

        # Execute batch
        results = await self._multicall.execute(calls)

        # Decode results
        positions = []
        for wallet, result in zip(wallet_addresses, results):
            success, decoded = self._multicall.decode_result(
                result, self.AAVE_OUTPUT_TYPES
            )

            if success and decoded:
                position_data = {
                    "total_collateral_base": decoded[0] / 1e8,
                    "total_debt_base": decoded[1] / 1e8,
                    "available_borrows_base": decoded[2] / 1e8,
                    "liquidation_threshold": decoded[3] / 1e4,
                    "ltv": decoded[4] / 1e4,
                    "health_factor": decoded[5] / 1e18 if decoded[5] < 2**255 else float("inf"),
                }
                positions.append((wallet, position_data))
            else:
                positions.append((wallet, None))

        return positions

    async def fetch_compound_borrow_balances(
        self,
        comet_address: str,
        wallet_addresses: List[str],
    ) -> List[Tuple[str, int | None]]:
        """
        Fetch multiple Compound V3 borrow balances in a single batched call.

        Args:
            comet_address: Compound V3 Comet contract address
            wallet_addresses: List of wallet addresses to check

        Returns:
            List of (wallet_address, borrow_balance) tuples
        """
        if not wallet_addresses:
            return []

        # Build calls for all wallets
        calls = [
            self._multicall.build_call(
                target=comet_address,
                function_signature="borrowBalanceOf(address)",
                input_types=["address"],
                input_values=[AsyncWeb3.to_checksum_address(addr)],
            )
            for addr in wallet_addresses
        ]

        # Execute batch
        results = await self._multicall.execute(calls)

        # Decode results
        balances = []
        for wallet, result in zip(wallet_addresses, results):
            success, decoded = self._multicall.decode_result(result, ["uint256"])

            if success and decoded:
                balances.append((wallet, decoded[0]))
            else:
                balances.append((wallet, None))

        return balances
