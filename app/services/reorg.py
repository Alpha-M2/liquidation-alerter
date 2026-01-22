"""
Chain reorg handling for reliable position monitoring.

Prevents false alerts by requiring multiple block confirmations
before considering a state change as finalized.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from collections import deque

from web3 import AsyncWeb3

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    """Represents a position's state at a specific block."""
    health_factor: float
    total_collateral_usd: float
    total_debt_usd: float
    block_number: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConfirmedState:
    """A confirmed position state after required block confirmations."""
    health_factor: float
    total_collateral_usd: float
    total_debt_usd: float
    is_critical: bool  # HF < 1.3
    is_liquidatable: bool  # HF <= 1.0
    confirmed_at_block: int
    first_seen_at_block: int


class ReorgSafeStateTracker:
    """
    Tracks position states across multiple blocks to handle chain reorgs.

    A state change is only considered confirmed after it has been observed
    consistently for a minimum number of blocks. This prevents false alerts
    that could occur if a block containing a critical state change gets
    reorged out.

    Configuration:
    - CONFIRMATION_BLOCKS: Number of blocks required to confirm a state change
    - CRITICAL_CONFIRMATION_BLOCKS: Fewer blocks for critical states (faster alerts)
    - STATE_HISTORY_SIZE: Number of historical states to keep per position
    """

    # Normal state changes require this many block confirmations
    CONFIRMATION_BLOCKS = 3

    # Critical state changes (HF < 1.3) use fewer confirmations for faster alerts
    CRITICAL_CONFIRMATION_BLOCKS = 2

    # Number of historical states to track
    STATE_HISTORY_SIZE = 10

    def __init__(self):
        # Track state history per wallet:protocol
        # Key: "wallet_address:protocol" -> deque of PositionState
        self._state_history: Dict[str, deque] = {}

        # Track confirmed states
        # Key: "wallet_address:protocol" -> ConfirmedState
        self._confirmed_states: Dict[str, ConfirmedState] = {}

        # Track current block numbers per chain
        self._block_numbers: Dict[str, int] = {}

    def _get_key(self, wallet_address: str, protocol: str) -> str:
        """Generate a unique key for wallet:protocol combination."""
        return f"{wallet_address.lower()}:{protocol}"

    def update_block_number(self, chain: str, block_number: int):
        """Update the current block number for a chain."""
        self._block_numbers[chain] = block_number

    def get_block_number(self, chain: str) -> int:
        """Get the current block number for a chain."""
        return self._block_numbers.get(chain, 0)

    def record_state(
        self,
        wallet_address: str,
        protocol: str,
        health_factor: float,
        total_collateral_usd: float,
        total_debt_usd: float,
        block_number: int,
    ) -> Tuple[bool, ConfirmedState | None]:
        """
        Record a position state observation.

        Args:
            wallet_address: Wallet address
            protocol: Protocol name
            health_factor: Current health factor
            total_collateral_usd: Current collateral value
            total_debt_usd: Current debt value
            block_number: Block number of the observation

        Returns:
            Tuple of (is_new_confirmed_state, confirmed_state)
            - is_new_confirmed_state: True if this observation resulted in a new confirmed state
            - confirmed_state: The confirmed state (None if not yet confirmed)
        """
        key = self._get_key(wallet_address, protocol)

        # Initialize history if needed
        if key not in self._state_history:
            self._state_history[key] = deque(maxlen=self.STATE_HISTORY_SIZE)

        # Add new state observation
        new_state = PositionState(
            health_factor=health_factor,
            total_collateral_usd=total_collateral_usd,
            total_debt_usd=total_debt_usd,
            block_number=block_number,
        )
        self._state_history[key].append(new_state)

        # Check if we have enough confirmations
        history = self._state_history[key]
        if len(history) < 2:
            return False, None

        # Determine required confirmations based on criticality
        is_critical = health_factor < 1.3
        is_liquidatable = health_factor <= 1.0

        required_blocks = (
            self.CRITICAL_CONFIRMATION_BLOCKS
            if is_critical or is_liquidatable
            else self.CONFIRMATION_BLOCKS
        )

        # Find the first block where this state was observed
        first_seen_block = block_number
        for state in history:
            if self._states_match(state, new_state):
                first_seen_block = min(first_seen_block, state.block_number)

        # Check if we have enough block confirmations
        blocks_confirmed = block_number - first_seen_block + 1

        if blocks_confirmed >= required_blocks:
            # State is confirmed
            confirmed = ConfirmedState(
                health_factor=health_factor,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                is_critical=is_critical,
                is_liquidatable=is_liquidatable,
                confirmed_at_block=block_number,
                first_seen_at_block=first_seen_block,
            )

            # Check if this is a NEW confirmed state (different from previous)
            previous_confirmed = self._confirmed_states.get(key)
            is_new = previous_confirmed is None or not self._confirmed_states_match(
                previous_confirmed, confirmed
            )

            self._confirmed_states[key] = confirmed
            return is_new, confirmed

        return False, self._confirmed_states.get(key)

    def _states_match(self, state1: PositionState, state2: PositionState) -> bool:
        """
        Check if two states are effectively the same.

        Uses a tolerance to account for minor fluctuations.
        """
        # Health factor tolerance: 1%
        hf_match = abs(state1.health_factor - state2.health_factor) / max(
            state1.health_factor, 0.001
        ) < 0.01

        # Collateral tolerance: 0.5%
        col_match = abs(
            state1.total_collateral_usd - state2.total_collateral_usd
        ) / max(state1.total_collateral_usd, 1) < 0.005

        # Debt tolerance: 0.5%
        debt_match = abs(state1.total_debt_usd - state2.total_debt_usd) / max(
            state1.total_debt_usd, 1
        ) < 0.005

        return hf_match and col_match and debt_match

    def _confirmed_states_match(
        self, state1: ConfirmedState, state2: ConfirmedState
    ) -> bool:
        """Check if two confirmed states represent the same critical status."""
        # For alerting purposes, we care about status changes
        return (
            state1.is_critical == state2.is_critical
            and state1.is_liquidatable == state2.is_liquidatable
        )

    def get_confirmed_state(
        self, wallet_address: str, protocol: str
    ) -> ConfirmedState | None:
        """Get the last confirmed state for a position."""
        key = self._get_key(wallet_address, protocol)
        return self._confirmed_states.get(key)

    def is_state_confirmed(
        self,
        wallet_address: str,
        protocol: str,
        health_factor: float,
    ) -> bool:
        """
        Check if a given health factor state is confirmed.

        Returns True if the state has been observed for enough blocks.
        """
        key = self._get_key(wallet_address, protocol)
        confirmed = self._confirmed_states.get(key)

        if confirmed is None:
            return False

        # Check if the confirmed state matches the given health factor
        is_critical = health_factor < 1.3
        is_liquidatable = health_factor <= 1.0

        return (
            confirmed.is_critical == is_critical
            and confirmed.is_liquidatable == is_liquidatable
        )

    def should_alert(
        self,
        wallet_address: str,
        protocol: str,
        health_factor: float,
        block_number: int,
    ) -> Tuple[bool, str | None]:
        """
        Determine if an alert should be sent for this position.

        Only alerts for confirmed state changes to prevent reorg-related
        false alerts.

        Args:
            wallet_address: Wallet address
            protocol: Protocol name
            health_factor: Current health factor
            block_number: Current block number

        Returns:
            Tuple of (should_alert, reason)
        """
        key = self._get_key(wallet_address, protocol)
        history = self._state_history.get(key)

        # First observation - don't alert yet
        if history is None or len(history) < 2:
            return False, "insufficient_history"

        # Check for confirmed state
        confirmed = self._confirmed_states.get(key)
        if confirmed is None:
            return False, "not_confirmed"

        # Alert if the confirmed state is critical or liquidatable
        if confirmed.is_liquidatable:
            return True, "confirmed_liquidatable"
        elif confirmed.is_critical:
            return True, "confirmed_critical"

        return False, "healthy"

    def clear_history(self, wallet_address: str, protocol: str | None = None):
        """Clear state history for a wallet."""
        if protocol:
            key = self._get_key(wallet_address, protocol)
            self._state_history.pop(key, None)
            self._confirmed_states.pop(key, None)
        else:
            # Clear all protocols for this wallet
            keys_to_remove = [
                k for k in self._state_history if k.startswith(wallet_address.lower())
            ]
            for key in keys_to_remove:
                self._state_history.pop(key, None)
                self._confirmed_states.pop(key, None)

    def get_stats(self) -> Dict[str, any]:
        """Get reorg tracker statistics."""
        pending_count = 0
        confirmed_count = 0
        critical_count = 0
        liquidatable_count = 0

        for key, confirmed in self._confirmed_states.items():
            confirmed_count += 1
            if confirmed.is_liquidatable:
                liquidatable_count += 1
            elif confirmed.is_critical:
                critical_count += 1

        pending_count = len(self._state_history) - confirmed_count

        return {
            "tracked_positions": len(self._state_history),
            "confirmed_states": confirmed_count,
            "pending_confirmation": pending_count,
            "critical_confirmed": critical_count,
            "liquidatable_confirmed": liquidatable_count,
        }


# Singleton instance
_reorg_tracker: ReorgSafeStateTracker | None = None


def get_reorg_tracker() -> ReorgSafeStateTracker:
    """Get the reorg-safe state tracker singleton."""
    global _reorg_tracker
    if _reorg_tracker is None:
        _reorg_tracker = ReorgSafeStateTracker()
    return _reorg_tracker
