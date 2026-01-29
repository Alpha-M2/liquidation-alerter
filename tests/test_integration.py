import os
import time

import pytest

from app.protocols.aave_v3 import AaveV3Adapter
from app.protocols.compound_v3 import CompoundV3Adapter

# Zero address - no position expected
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

has_ethereum_rpc = bool(os.getenv("ETHEREUM_RPC_URL"))
has_arbitrum_rpc = bool(os.getenv("ARBITRUM_RPC_URL"))
has_base_rpc = bool(os.getenv("BASE_RPC_URL"))
has_optimism_rpc = bool(os.getenv("OPTIMISM_RPC_URL"))


@pytest.mark.integration
@pytest.mark.skipif(not has_ethereum_rpc, reason="No ETHEREUM_RPC_URL configured")
class TestAaveV3Integration:
    @pytest.fixture
    def adapter(self):
        return AaveV3Adapter(chain="ethereum")

    async def test_get_position_real_rpc(self, adapter):
        """Test basic position fetch against live RPC - zero address should return None."""
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None

    async def test_get_detailed_position_real_rpc(self, adapter):
        """Test detailed position fetch against live RPC."""
        position = await adapter.get_detailed_position(ZERO_ADDRESS)
        assert position is None

    async def test_cache_improves_performance(self, adapter):
        """Test that second call is faster due to cache hit."""
        address = ZERO_ADDRESS

        start = time.time()
        await adapter.get_position(address)
        first_call_time = time.time() - start

        start = time.time()
        await adapter.get_position(address)
        second_call_time = time.time() - start

        # Second call should be significantly faster (cache hit)
        # Even a None result is cached, so second call should be near-instant
        assert second_call_time < first_call_time


@pytest.mark.integration
@pytest.mark.skipif(not has_ethereum_rpc, reason="No ETHEREUM_RPC_URL configured")
class TestCompoundV3Integration:
    @pytest.fixture
    def adapter(self):
        return CompoundV3Adapter(chain="ethereum")

    async def test_get_position_real_rpc(self, adapter):
        """Test basic position fetch against live RPC - zero address should return None."""
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None

    async def test_get_detailed_position_real_rpc(self, adapter):
        """Test detailed position fetch against live RPC."""
        position = await adapter.get_detailed_position(ZERO_ADDRESS)
        assert position is None

    async def test_cache_improves_performance(self, adapter):
        """Test that second call is faster due to cache hit."""
        address = ZERO_ADDRESS

        start = time.time()
        await adapter.get_position(address)
        first_call_time = time.time() - start

        start = time.time()
        await adapter.get_position(address)
        second_call_time = time.time() - start

        assert second_call_time < first_call_time


@pytest.mark.integration
@pytest.mark.skipif(not has_arbitrum_rpc, reason="No ARBITRUM_RPC_URL configured")
class TestMultiChainArbitrum:
    async def test_aave_v3_arbitrum(self):
        adapter = AaveV3Adapter(chain="arbitrum")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None

    async def test_compound_v3_arbitrum(self):
        adapter = CompoundV3Adapter(chain="arbitrum")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None


@pytest.mark.integration
@pytest.mark.skipif(not has_base_rpc, reason="No BASE_RPC_URL configured")
class TestMultiChainBase:
    async def test_aave_v3_base(self):
        adapter = AaveV3Adapter(chain="base")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None

    async def test_compound_v3_base(self):
        adapter = CompoundV3Adapter(chain="base")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None


@pytest.mark.integration
@pytest.mark.skipif(not has_optimism_rpc, reason="No OPTIMISM_RPC_URL configured")
class TestMultiChainOptimism:
    async def test_aave_v3_optimism(self):
        adapter = AaveV3Adapter(chain="optimism")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None

    async def test_compound_v3_optimism(self):
        adapter = CompoundV3Adapter(chain="optimism")
        position = await adapter.get_position(ZERO_ADDRESS)
        assert position is None
