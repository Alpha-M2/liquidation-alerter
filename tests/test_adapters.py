import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.protocols.aave_v3 import AaveV3Adapter
from app.protocols.compound_v3 import CompoundV3Adapter


class TestAaveV3Adapter:
    @pytest.fixture
    def mock_web3(self):
        web3 = MagicMock()
        web3.eth = MagicMock()
        return web3

    @pytest.fixture
    def adapter(self, mock_web3):
        return AaveV3Adapter(web3=mock_web3)

    def test_name(self, adapter):
        assert adapter.name == "Aave V3"

    @pytest.mark.asyncio
    async def test_get_position_with_data(self, adapter):
        # Mock contract call response
        # Format: (totalCollateralBase, totalDebtBase, availableBorrowsBase,
        #          currentLiquidationThreshold, ltv, healthFactor)
        mock_response = (
            100000000000,  # 1000 USD (8 decimals)
            50000000000,   # 500 USD
            20000000000,   # 200 USD
            8000,          # 80% (basis points)
            7500,          # 75% LTV
            2000000000000000000,  # 2.0 HF (18 decimals)
        )

        contract_mock = MagicMock()
        contract_mock.functions.getUserAccountData.return_value.call = AsyncMock(
            return_value=mock_response
        )
        adapter._pool_contract = contract_mock

        position = await adapter.get_position(
            "0x1234567890123456789012345678901234567890"
        )

        assert position is not None
        assert position.protocol == "Aave V3"
        assert position.total_collateral_usd == 1000.0
        assert position.total_debt_usd == 500.0
        assert position.health_factor == 2.0
        assert position.liquidation_threshold == 0.8

    @pytest.mark.asyncio
    async def test_get_position_no_data(self, adapter):
        mock_response = (0, 0, 0, 0, 0, 0)
        contract_mock = MagicMock()
        contract_mock.functions.getUserAccountData.return_value.call = AsyncMock(
            return_value=mock_response
        )
        adapter._pool_contract = contract_mock

        position = await adapter.get_position(
            "0x1234567890123456789012345678901234567890"
        )

        assert position is None

    @pytest.mark.asyncio
    async def test_has_position(self, adapter):
        mock_response = (
            100000000000,
            50000000000,
            20000000000,
            8000,
            7500,
            2000000000000000000,
        )
        contract_mock = MagicMock()
        contract_mock.functions.getUserAccountData.return_value.call = AsyncMock(
            return_value=mock_response
        )
        adapter._pool_contract = contract_mock

        has_pos = await adapter.has_position(
            "0x1234567890123456789012345678901234567890"
        )

        assert has_pos is True


class TestCompoundV3Adapter:
    @pytest.fixture
    def mock_web3(self):
        web3 = MagicMock()
        web3.eth = MagicMock()
        return web3

    @pytest.fixture
    def adapter(self, mock_web3):
        return CompoundV3Adapter(web3=mock_web3)

    def test_name(self, adapter):
        assert adapter.name == "Compound V3"

    @pytest.mark.asyncio
    async def test_is_liquidatable(self, adapter):
        contract_mock = MagicMock()
        contract_mock.functions.isLiquidatable.return_value.call = AsyncMock(
            return_value=False
        )
        adapter._comet_contract = contract_mock

        is_liq = await adapter.is_liquidatable(
            "0x1234567890123456789012345678901234567890"
        )

        assert is_liq is False
