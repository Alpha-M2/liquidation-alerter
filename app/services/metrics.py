"""
Prometheus metrics for the DeFi Liquidation Alerter.

Exposes key application metrics for monitoring and observability.
"""

import time
from functools import wraps
from typing import Callable

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
)

# Create a custom registry to avoid conflicts
REGISTRY = CollectorRegistry()

# Application info
APP_INFO = Info(
    "defi_alerter",
    "DeFi Liquidation Alerter application info",
    registry=REGISTRY,
)
APP_INFO.info({
    "version": "1.0.0",
    "name": "defi-liquidation-alerter",
})

# RPC metrics
RPC_REQUESTS_TOTAL = Counter(
    "defi_alerter_rpc_requests_total",
    "Total number of RPC requests",
    ["endpoint", "method", "status"],
    registry=REGISTRY,
)

RPC_REQUEST_DURATION_SECONDS = Histogram(
    "defi_alerter_rpc_request_duration_seconds",
    "RPC request duration in seconds",
    ["endpoint", "method"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

RPC_ERRORS_TOTAL = Counter(
    "defi_alerter_rpc_errors_total",
    "Total number of RPC errors",
    ["endpoint", "error_type"],
    registry=REGISTRY,
)

# Protocol metrics
POSITIONS_CHECKED_TOTAL = Counter(
    "defi_alerter_positions_checked_total",
    "Total number of positions checked",
    ["protocol"],
    registry=REGISTRY,
)

POSITION_HEALTH_FACTOR = Gauge(
    "defi_alerter_position_health_factor",
    "Current health factor of a position",
    ["protocol", "wallet"],
    registry=REGISTRY,
)

POSITION_COLLATERAL_USD = Gauge(
    "defi_alerter_position_collateral_usd",
    "Position collateral value in USD",
    ["protocol", "wallet"],
    registry=REGISTRY,
)

POSITION_DEBT_USD = Gauge(
    "defi_alerter_position_debt_usd",
    "Position debt value in USD",
    ["protocol", "wallet"],
    registry=REGISTRY,
)

# Alert metrics
ALERTS_SENT_TOTAL = Counter(
    "defi_alerter_alerts_sent_total",
    "Total number of alerts sent",
    ["protocol", "severity"],
    registry=REGISTRY,
)

ALERTS_FAILED_TOTAL = Counter(
    "defi_alerter_alerts_failed_total",
    "Total number of failed alert sends",
    ["protocol", "reason"],
    registry=REGISTRY,
)

# Price oracle metrics
ORACLE_REQUESTS_TOTAL = Counter(
    "defi_alerter_oracle_requests_total",
    "Total number of oracle price requests",
    ["source", "symbol", "status"],
    registry=REGISTRY,
)

ORACLE_PRICE = Gauge(
    "defi_alerter_oracle_price_usd",
    "Current price from oracle",
    ["source", "symbol"],
    registry=REGISTRY,
)

ORACLE_STALENESS_SECONDS = Gauge(
    "defi_alerter_oracle_staleness_seconds",
    "Age of the oracle price in seconds",
    ["source", "symbol"],
    registry=REGISTRY,
)

# Gas metrics
GAS_PRICE_GWEI = Gauge(
    "defi_alerter_gas_price_gwei",
    "Current gas price in Gwei",
    registry=REGISTRY,
)

# Liquidation cascade metrics
LIQUIDATIONS_DETECTED_TOTAL = Counter(
    "defi_alerter_liquidations_detected_total",
    "Total number of liquidations detected",
    ["protocol"],
    registry=REGISTRY,
)

LIQUIDATION_VALUE_USD_TOTAL = Counter(
    "defi_alerter_liquidation_value_usd_total",
    "Total value of liquidations in USD",
    ["protocol"],
    registry=REGISTRY,
)

CASCADE_ALERTS_TOTAL = Counter(
    "defi_alerter_cascade_alerts_total",
    "Total number of cascade alerts",
    ["protocol", "severity"],
    registry=REGISTRY,
)

# User metrics
ACTIVE_USERS = Gauge(
    "defi_alerter_active_users",
    "Number of active users",
    registry=REGISTRY,
)

MONITORED_WALLETS = Gauge(
    "defi_alerter_monitored_wallets",
    "Number of monitored wallets",
    registry=REGISTRY,
)

# Monitoring cycle metrics
MONITORING_CYCLE_DURATION_SECONDS = Histogram(
    "defi_alerter_monitoring_cycle_duration_seconds",
    "Duration of monitoring cycles in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=REGISTRY,
)

MONITORING_CYCLES_TOTAL = Counter(
    "defi_alerter_monitoring_cycles_total",
    "Total number of monitoring cycles",
    ["status"],
    registry=REGISTRY,
)


def get_metrics() -> bytes:
    """Get all metrics in Prometheus format."""
    return generate_latest(REGISTRY)


def get_content_type() -> str:
    """Get the Prometheus content type."""
    return CONTENT_TYPE_LATEST


def track_rpc_request(endpoint: str, method: str):
    """Decorator to track RPC request metrics."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                RPC_ERRORS_TOTAL.labels(endpoint=endpoint, error_type=type(e).__name__).inc()
                raise
            finally:
                duration = time.time() - start_time
                RPC_REQUESTS_TOTAL.labels(endpoint=endpoint, method=method, status=status).inc()
                RPC_REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, method=method).observe(duration)
        return wrapper
    return decorator


def record_position_metrics(protocol: str, wallet: str, health_factor: float, collateral_usd: float, debt_usd: float):
    """Record metrics for a position."""
    # Use short wallet address for labels
    short_wallet = f"{wallet[:6]}...{wallet[-4:]}"

    POSITIONS_CHECKED_TOTAL.labels(protocol=protocol).inc()
    POSITION_HEALTH_FACTOR.labels(protocol=protocol, wallet=short_wallet).set(health_factor)
    POSITION_COLLATERAL_USD.labels(protocol=protocol, wallet=short_wallet).set(collateral_usd)
    POSITION_DEBT_USD.labels(protocol=protocol, wallet=short_wallet).set(debt_usd)


def record_alert_sent(protocol: str, severity: str):
    """Record that an alert was sent."""
    ALERTS_SENT_TOTAL.labels(protocol=protocol, severity=severity).inc()


def record_alert_failed(protocol: str, reason: str):
    """Record that an alert failed to send."""
    ALERTS_FAILED_TOTAL.labels(protocol=protocol, reason=reason).inc()


def record_liquidation(protocol: str, value_usd: float):
    """Record a detected liquidation."""
    LIQUIDATIONS_DETECTED_TOTAL.labels(protocol=protocol).inc()
    LIQUIDATION_VALUE_USD_TOTAL.labels(protocol=protocol).inc(value_usd)


def record_cascade_alert(protocol: str, severity: str):
    """Record a cascade alert."""
    CASCADE_ALERTS_TOTAL.labels(protocol=protocol, severity=severity).inc()


def update_gas_price(gwei: float):
    """Update current gas price metric."""
    GAS_PRICE_GWEI.set(gwei)


def update_user_counts(active_users: int, monitored_wallets: int):
    """Update user count metrics."""
    ACTIVE_USERS.set(active_users)
    MONITORED_WALLETS.set(monitored_wallets)


class MonitoringCycleTimer:
    """Context manager for timing monitoring cycles."""

    def __init__(self):
        self._start_time = None

    def __enter__(self):
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self._start_time
        MONITORING_CYCLE_DURATION_SECONDS.observe(duration)

        status = "success" if exc_type is None else "error"
        MONITORING_CYCLES_TOTAL.labels(status=status).inc()

        return False  # Don't suppress exceptions
