"""Token metadata caching service for ERC20 tokens.

This service provides token symbol, decimals, and name information
with caching to minimize RPC calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from web3 import AsyncWeb3


@dataclass
class TokenMetadata:
    """ERC20 token metadata."""
    address: str
    symbol: str
    decimals: int
    name: str | None = None


# ERC20 ABI for metadata calls
ERC20_METADATA_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "name",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class TokenMetadataService:
    """Caching service for ERC20 token metadata.

    Provides token symbol, decimals, and name with in-memory caching.
    Common tokens are hardcoded to avoid RPC calls.
    """

    # Hardcoded metadata for common tokens (avoid RPC calls)
    # Format: chain -> address -> TokenMetadata
    KNOWN_TOKENS: Dict[str, Dict[str, TokenMetadata]] = {
        "ethereum": {
            # Stablecoins
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48": TokenMetadata(
                address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                symbol="USDC",
                decimals=6,
                name="USD Coin",
            ),
            "0xdAC17F958D2ee523a2206206994597C13D831ec7": TokenMetadata(
                address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
                symbol="USDT",
                decimals=6,
                name="Tether USD",
            ),
            "0x6B175474E89094C44Da98b954EedeAC495271d0F": TokenMetadata(
                address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
                symbol="DAI",
                decimals=18,
                name="Dai Stablecoin",
            ),
            "0x853d955aCEf822Db058eb8505911ED77F175b99e": TokenMetadata(
                address="0x853d955aCEf822Db058eb8505911ED77F175b99e",
                symbol="FRAX",
                decimals=18,
                name="Frax",
            ),
            "0x5f98805A4E8be255a32880FDeC7F6728C6568bA0": TokenMetadata(
                address="0x5f98805A4E8be255a32880FDeC7F6728C6568bA0",
                symbol="LUSD",
                decimals=18,
                name="Liquity USD",
            ),
            # Major assets
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": TokenMetadata(
                address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                symbol="WETH",
                decimals=18,
                name="Wrapped Ether",
            ),
            "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": TokenMetadata(
                address="0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
                symbol="WBTC",
                decimals=8,
                name="Wrapped BTC",
            ),
            # Liquid Staking Derivatives (LSDs)
            "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84": TokenMetadata(
                address="0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                symbol="stETH",
                decimals=18,
                name="Lido Staked Ether",
            ),
            "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0": TokenMetadata(
                address="0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                symbol="wstETH",
                decimals=18,
                name="Wrapped stETH",
            ),
            "0xae78736Cd615f374D3085123A210448E74Fc6393": TokenMetadata(
                address="0xae78736Cd615f374D3085123A210448E74Fc6393",
                symbol="rETH",
                decimals=18,
                name="Rocket Pool ETH",
            ),
            "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704": TokenMetadata(
                address="0xBe9895146f7AF43049ca1c1AE358B0541Ea49704",
                symbol="cbETH",
                decimals=18,
                name="Coinbase Wrapped Staked ETH",
            ),
            # DeFi tokens
            "0x514910771AF9Ca656af840dff83E8264EcF986CA": TokenMetadata(
                address="0x514910771AF9Ca656af840dff83E8264EcF986CA",
                symbol="LINK",
                decimals=18,
                name="Chainlink",
            ),
            "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984": TokenMetadata(
                address="0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
                symbol="UNI",
                decimals=18,
                name="Uniswap",
            ),
            "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9": TokenMetadata(
                address="0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
                symbol="AAVE",
                decimals=18,
                name="Aave",
            ),
            "0xD533a949740bb3306d119CC777fa900bA034cd52": TokenMetadata(
                address="0xD533a949740bb3306d119CC777fa900bA034cd52",
                symbol="CRV",
                decimals=18,
                name="Curve DAO Token",
            ),
            "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2": TokenMetadata(
                address="0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
                symbol="MKR",
                decimals=18,
                name="Maker",
            ),
            "0xc00e94Cb662C3520282E6f5717214004A7f26888": TokenMetadata(
                address="0xc00e94Cb662C3520282E6f5717214004A7f26888",
                symbol="COMP",
                decimals=18,
                name="Compound",
            ),
        },
        "arbitrum": {
            # USDC (native)
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831": TokenMetadata(
                address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                symbol="USDC",
                decimals=6,
                name="USD Coin",
            ),
            # USDC.e (bridged)
            "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8": TokenMetadata(
                address="0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
                symbol="USDC.e",
                decimals=6,
                name="Bridged USDC",
            ),
            "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9": TokenMetadata(
                address="0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
                symbol="USDT",
                decimals=6,
                name="Tether USD",
            ),
            "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1": TokenMetadata(
                address="0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
                symbol="DAI",
                decimals=18,
                name="Dai Stablecoin",
            ),
            "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1": TokenMetadata(
                address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                symbol="WETH",
                decimals=18,
                name="Wrapped Ether",
            ),
            "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f": TokenMetadata(
                address="0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
                symbol="WBTC",
                decimals=8,
                name="Wrapped BTC",
            ),
            "0x5979D7b546E38E414F7E9822514be443A4800529": TokenMetadata(
                address="0x5979D7b546E38E414F7E9822514be443A4800529",
                symbol="wstETH",
                decimals=18,
                name="Wrapped stETH",
            ),
            "0xEC70Dcb4A1EFa46b8F2D97C310C9c4790ba5ffA8": TokenMetadata(
                address="0xEC70Dcb4A1EFa46b8F2D97C310C9c4790ba5ffA8",
                symbol="rETH",
                decimals=18,
                name="Rocket Pool ETH",
            ),
            "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4": TokenMetadata(
                address="0xf97f4df75117a78c1A5a0DBb814Af92458539FB4",
                symbol="LINK",
                decimals=18,
                name="Chainlink",
            ),
            "0x912CE59144191C1204E64559FE8253a0e49E6548": TokenMetadata(
                address="0x912CE59144191C1204E64559FE8253a0e49E6548",
                symbol="ARB",
                decimals=18,
                name="Arbitrum",
            ),
        },
        "base": {
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": TokenMetadata(
                address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                symbol="USDC",
                decimals=6,
                name="USD Coin",
            ),
            "0x4200000000000000000000000000000000000006": TokenMetadata(
                address="0x4200000000000000000000000000000000000006",
                symbol="WETH",
                decimals=18,
                name="Wrapped Ether",
            ),
            "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb": TokenMetadata(
                address="0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
                symbol="DAI",
                decimals=18,
                name="Dai Stablecoin",
            ),
            "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452": TokenMetadata(
                address="0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
                symbol="wstETH",
                decimals=18,
                name="Wrapped stETH",
            ),
            "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22": TokenMetadata(
                address="0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
                symbol="cbETH",
                decimals=18,
                name="Coinbase Wrapped Staked ETH",
            ),
        },
        "optimism": {
            "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85": TokenMetadata(
                address="0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                symbol="USDC",
                decimals=6,
                name="USD Coin",
            ),
            "0x7F5c764cBc14f9669B88837ca1490cCa17c31607": TokenMetadata(
                address="0x7F5c764cBc14f9669B88837ca1490cCa17c31607",
                symbol="USDC.e",
                decimals=6,
                name="Bridged USDC",
            ),
            "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58": TokenMetadata(
                address="0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
                symbol="USDT",
                decimals=6,
                name="Tether USD",
            ),
            "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1": TokenMetadata(
                address="0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
                symbol="DAI",
                decimals=18,
                name="Dai Stablecoin",
            ),
            "0x4200000000000000000000000000000000000006": TokenMetadata(
                address="0x4200000000000000000000000000000000000006",
                symbol="WETH",
                decimals=18,
                name="Wrapped Ether",
            ),
            "0x68f180fcCe6836688e9084f035309E29Bf0A2095": TokenMetadata(
                address="0x68f180fcCe6836688e9084f035309E29Bf0A2095",
                symbol="WBTC",
                decimals=8,
                name="Wrapped BTC",
            ),
            "0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb": TokenMetadata(
                address="0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb",
                symbol="wstETH",
                decimals=18,
                name="Wrapped stETH",
            ),
            "0x9Bcef72be871e61ED4fBbc7630889beE758eb81D": TokenMetadata(
                address="0x9Bcef72be871e61ED4fBbc7630889beE758eb81D",
                symbol="rETH",
                decimals=18,
                name="Rocket Pool ETH",
            ),
            "0x4200000000000000000000000000000000000042": TokenMetadata(
                address="0x4200000000000000000000000000000000000042",
                symbol="OP",
                decimals=18,
                name="Optimism",
            ),
        },
    }

    def __init__(self, web3_provider: AsyncWeb3 | None = None):
        self._cache: Dict[str, TokenMetadata] = {}
        self._web3 = web3_provider

    def _cache_key(self, address: str, chain: str) -> str:
        """Generate cache key for address:chain."""
        return f"{chain}:{address.lower()}"

    def _normalize_address(self, address: str) -> str:
        """Normalize address to checksum format."""
        return AsyncWeb3.to_checksum_address(address)

    async def get_metadata(
        self,
        address: str,
        chain: str = "ethereum",
        web3: AsyncWeb3 | None = None,
    ) -> TokenMetadata | None:
        """Get token metadata from cache, hardcoded list, or RPC.

        Args:
            address: Token contract address
            chain: Chain name (ethereum, arbitrum, base, optimism)
            web3: Optional Web3 instance for RPC calls

        Returns:
            TokenMetadata or None if not found
        """
        checksum_address = self._normalize_address(address)
        cache_key = self._cache_key(checksum_address, chain)

        # Check runtime cache first
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check hardcoded tokens
        chain_tokens = self.KNOWN_TOKENS.get(chain, {})
        if checksum_address in chain_tokens:
            metadata = chain_tokens[checksum_address]
            self._cache[cache_key] = metadata
            return metadata

        # Try RPC call if web3 provided
        web3_instance = web3 or self._web3
        if web3_instance:
            try:
                metadata = await self._fetch_from_rpc(checksum_address, web3_instance)
                if metadata:
                    self._cache[cache_key] = metadata
                    return metadata
            except Exception:
                pass  # Silently fail, return None

        return None

    async def _fetch_from_rpc(
        self,
        address: str,
        web3: AsyncWeb3,
    ) -> TokenMetadata | None:
        """Fetch token metadata from RPC."""
        try:
            contract = web3.eth.contract(
                address=address,
                abi=ERC20_METADATA_ABI,
            )

            # Fetch symbol and decimals (name is optional)
            symbol = await contract.functions.symbol().call()
            decimals = await contract.functions.decimals().call()

            name = None
            try:
                name = await contract.functions.name().call()
            except Exception:
                pass  # Name is optional

            return TokenMetadata(
                address=address,
                symbol=symbol,
                decimals=decimals,
                name=name,
            )
        except Exception:
            return None

    async def get_metadata_batch(
        self,
        addresses: List[str],
        chain: str = "ethereum",
        web3: AsyncWeb3 | None = None,
    ) -> Dict[str, TokenMetadata]:
        """Get metadata for multiple tokens.

        Args:
            addresses: List of token addresses
            chain: Chain name
            web3: Optional Web3 instance for RPC calls

        Returns:
            Dict mapping address -> TokenMetadata
        """
        result = {}
        for address in addresses:
            metadata = await self.get_metadata(address, chain, web3)
            if metadata:
                result[self._normalize_address(address)] = metadata
        return result

    def get_known_token(self, address: str, chain: str = "ethereum") -> TokenMetadata | None:
        """Get metadata for a known token (no RPC call).

        Args:
            address: Token contract address
            chain: Chain name

        Returns:
            TokenMetadata or None if not in hardcoded list
        """
        checksum_address = self._normalize_address(address)
        chain_tokens = self.KNOWN_TOKENS.get(chain, {})
        return chain_tokens.get(checksum_address)


# Singleton instance
_token_metadata_service: TokenMetadataService | None = None


def get_token_metadata_service() -> TokenMetadataService:
    """Get the singleton TokenMetadataService instance."""
    global _token_metadata_service
    if _token_metadata_service is None:
        _token_metadata_service = TokenMetadataService()
    return _token_metadata_service
