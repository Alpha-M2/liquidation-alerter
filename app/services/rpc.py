"""RPC provider with fallback and rate limiting.

This module provides a robust Web3 RPC provider with automatic failover
between multiple endpoints, rate limiting, and call tracking for monitoring.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import List

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RPCEndpoint:
    url: str
    name: str
    priority: int = 0
    failures: int = 0
    last_failure: float = 0


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, calls_per_second: float = 10):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a call is allowed."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_call_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self.last_call_time = time.time()


class CallTracker:
    """Track RPC call statistics."""

    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self.calls: deque = deque()
        self.errors: deque = deque()

    def record_call(self, success: bool = True):
        now = time.time()
        self.calls.append(now)
        if not success:
            self.errors.append(now)
        self._cleanup(now)

    def _cleanup(self, now: float):
        cutoff = now - self.window_seconds
        while self.calls and self.calls[0] < cutoff:
            self.calls.popleft()
        while self.errors and self.errors[0] < cutoff:
            self.errors.popleft()

    @property
    def calls_per_minute(self) -> int:
        self._cleanup(time.time())
        return len(self.calls)

    @property
    def error_rate(self) -> float:
        if not self.calls:
            return 0.0
        return len(self.errors) / len(self.calls)


class FallbackWeb3Provider:
    """
    Web3 provider with multiple RPC endpoints and automatic fallback.

    Features:
    - Multiple RPC endpoint support
    - Automatic failover on errors
    - Rate limiting per endpoint
    - Health tracking and endpoint rotation
    """

    FAILURE_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        endpoints: List[str] | None = None,
        calls_per_second: float = 10,
    ):
        settings = get_settings()

        # Build endpoint list
        if endpoints:
            self._endpoints = [
                RPCEndpoint(url=url, name=f"endpoint_{i}", priority=i)
                for i, url in enumerate(endpoints)
            ]
        else:
            # Use primary from settings, can add fallbacks
            self._endpoints = [
                RPCEndpoint(url=settings.rpc_url, name="primary", priority=0),
            ]

        self._rate_limiter = RateLimiter(calls_per_second)
        self._call_tracker = CallTracker()
        self._current_endpoint_idx = 0
        self._web3_instances: dict[str, AsyncWeb3] = {}

    def _get_web3_for_endpoint(self, endpoint: RPCEndpoint) -> AsyncWeb3:
        """Get or create Web3 instance for an endpoint."""
        if endpoint.url not in self._web3_instances:
            self._web3_instances[endpoint.url] = AsyncWeb3(
                AsyncHTTPProvider(endpoint.url),
                modules={"eth": (AsyncEth,)},
            )
        return self._web3_instances[endpoint.url]

    def _get_available_endpoint(self) -> RPCEndpoint | None:
        """Get the next available endpoint that isn't in cooldown."""
        now = time.time()

        # Sort by priority, then failures
        sorted_endpoints = sorted(
            self._endpoints,
            key=lambda e: (e.failures, e.priority),
        )

        for endpoint in sorted_endpoints:
            # Skip endpoints in cooldown
            if endpoint.failures > 0:
                cooldown_remaining = (
                    endpoint.last_failure + self.FAILURE_COOLDOWN_SECONDS - now
                )
                if cooldown_remaining > 0:
                    continue
                else:
                    # Reset failures after cooldown
                    endpoint.failures = 0

            return endpoint

        # All endpoints in cooldown, return least recently failed
        return sorted_endpoints[0] if sorted_endpoints else None

    def _mark_endpoint_failed(self, endpoint: RPCEndpoint):
        """Mark an endpoint as failed."""
        endpoint.failures += 1
        endpoint.last_failure = time.time()
        logger.warning(
            f"RPC endpoint {endpoint.name} failed "
            f"(total failures: {endpoint.failures})"
        )

    def _mark_endpoint_success(self, endpoint: RPCEndpoint):
        """Mark an endpoint as successful."""
        endpoint.failures = 0

    async def get_web3(self) -> AsyncWeb3:
        """Get Web3 instance with rate limiting and fallback."""
        await self._rate_limiter.acquire()

        endpoint = self._get_available_endpoint()
        if endpoint is None:
            raise RuntimeError("No RPC endpoints available")

        return self._get_web3_for_endpoint(endpoint)

    async def execute_with_fallback(self, func, *args, **kwargs):
        """
        Execute a function with automatic fallback to other endpoints on failure.
        """
        last_error = None

        for _ in range(len(self._endpoints)):
            endpoint = self._get_available_endpoint()
            if endpoint is None:
                break

            try:
                await self._rate_limiter.acquire()
                web3 = self._get_web3_for_endpoint(endpoint)
                result = await func(web3, *args, **kwargs)
                self._mark_endpoint_success(endpoint)
                self._call_tracker.record_call(success=True)
                return result
            except Exception as e:
                last_error = e
                self._mark_endpoint_failed(endpoint)
                self._call_tracker.record_call(success=False)
                logger.error(f"RPC call failed on {endpoint.name}: {e}")
                continue

        raise last_error or RuntimeError("All RPC endpoints failed")

    @property
    def stats(self) -> dict:
        """Get RPC statistics."""
        return {
            "calls_per_minute": self._call_tracker.calls_per_minute,
            "error_rate": self._call_tracker.error_rate,
            "endpoints": [
                {
                    "name": e.name,
                    "failures": e.failures,
                    "priority": e.priority,
                }
                for e in self._endpoints
            ],
        }


# Singleton instances
_web3_provider: FallbackWeb3Provider | None = None
_web3_instance: AsyncWeb3 | None = None


def get_web3_provider() -> FallbackWeb3Provider:
    """Get the fallback Web3 provider."""
    global _web3_provider
    if _web3_provider is None:
        _web3_provider = FallbackWeb3Provider()
    return _web3_provider


def get_web3() -> AsyncWeb3:
    """Get Web3 instance (simple, for backward compatibility)."""
    global _web3_instance
    if _web3_instance is None:
        settings = get_settings()
        _web3_instance = AsyncWeb3(
            AsyncHTTPProvider(settings.rpc_url),
            modules={"eth": (AsyncEth,)},
        )
    return _web3_instance


class Web3Provider:
    """Legacy compatibility class."""

    _instance: AsyncWeb3 | None = None

    @classmethod
    def get_web3(cls) -> AsyncWeb3:
        return get_web3()

    @classmethod
    async def is_connected(cls) -> bool:
        web3 = cls.get_web3()
        return await web3.is_connected()
