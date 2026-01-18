"""Tests for liquidation cascade detection."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.cascade import (
    LiquidationEvent,
    CascadeAlert,
    LiquidationCascadeDetector,
)


class TestLiquidationCascadeDetector:
    @pytest.fixture
    def detector(self):
        with patch('app.core.cascade.get_web3_provider') as mock:
            mock.return_value = MagicMock()
            return LiquidationCascadeDetector()

    def test_init(self, detector):
        assert detector._recent_liquidations == {}
        assert detector._last_checked_block == {}
        assert detector._alert_history == {}

    def test_cleanup_old_events(self, detector):
        protocol = "Aave V3"

        # Add old and new events
        old_event = LiquidationEvent(
            protocol=protocol,
            block_number=1000,
            tx_hash="0x123",
            liquidator="0xabc",
            borrower="0xdef",
            debt_covered_usd=1000,
            collateral_seized_usd=1100,
            timestamp=datetime.utcnow() - timedelta(hours=2),
        )

        new_event = LiquidationEvent(
            protocol=protocol,
            block_number=2000,
            tx_hash="0x456",
            liquidator="0xabc",
            borrower="0xghi",
            debt_covered_usd=2000,
            collateral_seized_usd=2200,
            timestamp=datetime.utcnow(),
        )

        detector._recent_liquidations[protocol] = [old_event, new_event]
        detector._cleanup_old_events(protocol)

        # Old event should be removed
        assert len(detector._recent_liquidations[protocol]) == 1
        assert detector._recent_liquidations[protocol][0].tx_hash == "0x456"

    def test_detect_cascade_no_events(self, detector):
        result = detector._detect_cascade("Aave V3")
        assert result is None

    def test_detect_cascade_below_threshold(self, detector):
        protocol = "Aave V3"

        # Add 3 events (below warning threshold of 5)
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=10000,
                collateral_seized_usd=11000,
                timestamp=datetime.utcnow(),
            )
            for i in range(3)
        ]

        detector._recent_liquidations[protocol] = events
        result = detector._detect_cascade(protocol)

        assert result is None

    def test_detect_cascade_warning_by_count(self, detector):
        protocol = "Aave V3"

        # Add 6 events (above warning threshold of 5)
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=10000,
                collateral_seized_usd=11000,
                timestamp=datetime.utcnow(),
            )
            for i in range(6)
        ]

        detector._recent_liquidations[protocol] = events
        result = detector._detect_cascade(protocol)

        assert result is not None
        assert result.severity == "warning"
        assert result.liquidation_count == 6

    def test_detect_cascade_critical_by_value(self, detector):
        protocol = "Aave V3"

        # Add 3 events with high value (above critical threshold of $5M)
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=2_000_000,  # $2M each
                collateral_seized_usd=2_200_000,
                timestamp=datetime.utcnow(),
            )
            for i in range(3)
        ]

        detector._recent_liquidations[protocol] = events
        result = detector._detect_cascade(protocol)

        assert result is not None
        assert result.severity == "critical"
        assert result.total_value_usd == 6_000_000

    def test_detect_cascade_severe(self, detector):
        protocol = "Aave V3"

        # Add 25 events (above severe threshold of 20)
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=100_000,
                collateral_seized_usd=110_000,
                timestamp=datetime.utcnow(),
            )
            for i in range(25)
        ]

        detector._recent_liquidations[protocol] = events
        result = detector._detect_cascade(protocol)

        assert result is not None
        assert result.severity == "severe"

    def test_cascade_alert_cooldown(self, detector):
        protocol = "Aave V3"

        # Add events above threshold
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=100_000,
                collateral_seized_usd=110_000,
                timestamp=datetime.utcnow(),
            )
            for i in range(10)
        ]

        detector._recent_liquidations[protocol] = events

        # First detection should trigger alert
        result1 = detector._detect_cascade(protocol)
        assert result1 is not None

        # Second detection should be blocked by cooldown
        result2 = detector._detect_cascade(protocol)
        assert result2 is None

    def test_get_recent_liquidations(self, detector):
        protocol = "Aave V3"
        event = LiquidationEvent(
            protocol=protocol,
            block_number=1000,
            tx_hash="0x123",
            liquidator="0xabc",
            borrower="0xdef",
            debt_covered_usd=1000,
            collateral_seized_usd=1100,
            timestamp=datetime.utcnow(),
        )

        detector._recent_liquidations[protocol] = [event]
        result = detector.get_recent_liquidations(protocol)

        assert len(result) == 1
        assert result[0].tx_hash == "0x123"

    def test_get_recent_liquidations_empty(self, detector):
        result = detector.get_recent_liquidations("Unknown Protocol")
        assert result == []

    def test_get_stats(self, detector):
        protocol = "Aave V3"
        events = [
            LiquidationEvent(
                protocol=protocol,
                block_number=i,
                tx_hash=f"0x{i}",
                liquidator="0xabc",
                borrower=f"0x{i}",
                debt_covered_usd=1000 * (i + 1),
                collateral_seized_usd=1100 * (i + 1),
                timestamp=datetime.utcnow(),
            )
            for i in range(3)
        ]

        detector._recent_liquidations[protocol] = events
        stats = detector.get_stats()

        assert protocol in stats
        assert stats[protocol]["recent_count"] == 3
        assert stats[protocol]["total_value_usd"] == 6000  # 1000 + 2000 + 3000
