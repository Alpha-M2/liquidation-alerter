"""Caching service for reducing RPC calls and improving performance.

This module provides TTL-based caching for position data and reserve data
to minimize redundant RPC calls during monitoring cycles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Generic, TypeVar, Any, Optional

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """Cache entry with TTL tracking."""
    value: T
    created_at: float
    ttl_seconds: float

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return time.time() - self.created_at > self.ttl_seconds

    def remaining_ttl(self) -> float:
        """Return remaining TTL in seconds (negative if expired)."""
        return self.ttl_seconds - (time.time() - self.created_at)


class TTLCache(Generic[T]):
    """Generic TTL-based cache.

    Items expire after the specified TTL and are lazily cleaned up.
    """

    def __init__(self, default_ttl_seconds: float = 60.0):
        self._cache: Dict[str, CacheEntry[T]] = {}
        self._default_ttl = default_ttl_seconds
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        return entry.value

    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None:
        """Set value in cache with optional custom TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Optional custom TTL (uses default if None)
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._cache[key] = CacheEntry(
            value=value,
            created_at=time.time(),
            ttl_seconds=ttl,
        )

    def delete(self, key: str) -> bool:
        """Delete an entry from the cache.

        Args:
            key: Cache key

        Returns:
            True if entry was deleted, False if not found
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> int:
        """Clear all entries from the cache.

        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0

        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_percent": hit_rate,
        }


class PositionCache:
    """Cache for position data with wallet+protocol keying.

    Optimized for the monitoring engine to reduce RPC calls during
    rapid health checks.
    """

    # Default TTL for position data (30 seconds for detailed, 60 for basic)
    DETAILED_TTL = 30.0
    BASIC_TTL = 60.0

    def __init__(self):
        self._basic_cache: TTLCache[Dict] = TTLCache(default_ttl_seconds=self.BASIC_TTL)
        self._detailed_cache: TTLCache[Dict] = TTLCache(default_ttl_seconds=self.DETAILED_TTL)

    def _make_key(self, wallet_address: str, protocol: str) -> str:
        """Generate cache key from wallet and protocol."""
        return f"{wallet_address.lower()}:{protocol}"

    def get_basic(self, wallet_address: str, protocol: str) -> Optional[Dict]:
        """Get cached basic position data."""
        key = self._make_key(wallet_address, protocol)
        return self._basic_cache.get(key)

    def set_basic(self, wallet_address: str, protocol: str, data: Dict) -> None:
        """Cache basic position data."""
        key = self._make_key(wallet_address, protocol)
        self._basic_cache.set(key, data)

    def get_detailed(self, wallet_address: str, protocol: str) -> Optional[Dict]:
        """Get cached detailed position data."""
        key = self._make_key(wallet_address, protocol)
        return self._detailed_cache.get(key)

    def set_detailed(self, wallet_address: str, protocol: str, data: Dict) -> None:
        """Cache detailed position data."""
        key = self._make_key(wallet_address, protocol)
        self._detailed_cache.set(key, data)

    def invalidate(self, wallet_address: str, protocol: str) -> None:
        """Invalidate cache for a specific wallet+protocol."""
        key = self._make_key(wallet_address, protocol)
        self._basic_cache.delete(key)
        self._detailed_cache.delete(key)

    def invalidate_wallet(self, wallet_address: str) -> None:
        """Invalidate all cache entries for a wallet (all protocols)."""
        prefix = f"{wallet_address.lower()}:"
        # Remove from basic cache
        keys_to_remove = [k for k in self._basic_cache._cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            self._basic_cache.delete(key)
        # Remove from detailed cache
        keys_to_remove = [k for k in self._detailed_cache._cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            self._detailed_cache.delete(key)

    def cleanup(self) -> Dict[str, int]:
        """Clean up expired entries from all caches.

        Returns:
            Dict with cleanup stats
        """
        return {
            "basic_cleaned": self._basic_cache.cleanup_expired(),
            "detailed_cleaned": self._detailed_cache.cleanup_expired(),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get combined cache statistics."""
        basic_stats = self._basic_cache.get_stats()
        detailed_stats = self._detailed_cache.get_stats()

        return {
            "basic": basic_stats,
            "detailed": detailed_stats,
            "total_entries": basic_stats["entries"] + detailed_stats["entries"],
        }


class ReserveDataCache:
    """Cache for protocol reserve data (token info, prices, APYs).

    Reserve data changes less frequently than position data, so it
    can have a longer TTL.
    """

    # Reserve data TTL (2 minutes - prices update frequently)
    RESERVE_TTL = 120.0

    def __init__(self):
        self._cache: TTLCache[Dict] = TTLCache(default_ttl_seconds=self.RESERVE_TTL)

    def _make_key(self, protocol: str, chain: str) -> str:
        """Generate cache key from protocol and chain."""
        return f"{protocol}:{chain}"

    def get(self, protocol: str, chain: str) -> Optional[Dict]:
        """Get cached reserve data."""
        key = self._make_key(protocol, chain)
        return self._cache.get(key)

    def set(self, protocol: str, chain: str, data: Dict) -> None:
        """Cache reserve data."""
        key = self._make_key(protocol, chain)
        self._cache.set(key, data)

    def invalidate(self, protocol: str, chain: str) -> None:
        """Invalidate cache for a specific protocol+chain."""
        key = self._make_key(protocol, chain)
        self._cache.delete(key)

    def clear(self) -> int:
        """Clear all reserve data cache."""
        return self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.get_stats()


# Singleton instances
_position_cache: PositionCache | None = None
_reserve_cache: ReserveDataCache | None = None


def get_position_cache() -> PositionCache:
    """Get the singleton PositionCache instance."""
    global _position_cache
    if _position_cache is None:
        _position_cache = PositionCache()
    return _position_cache


def get_reserve_cache() -> ReserveDataCache:
    """Get the singleton ReserveDataCache instance."""
    global _reserve_cache
    if _reserve_cache is None:
        _reserve_cache = ReserveDataCache()
    return _reserve_cache
