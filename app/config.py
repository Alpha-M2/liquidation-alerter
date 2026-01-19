from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    telegram_bot_token: str = Field(..., description="Telegram Bot API token")

    # Primary RPC URL (Ethereum mainnet, also used as fallback for other chains)
    rpc_url: str = Field(..., description="Ethereum RPC URL")

    # Chain-specific RPC URLs (optional - falls back to rpc_url if not set)
    ethereum_rpc_url: str | None = Field(
        default=None, description="Ethereum mainnet RPC URL (optional, uses rpc_url if not set)"
    )
    arbitrum_rpc_url: str | None = Field(
        default=None, description="Arbitrum One RPC URL"
    )
    base_rpc_url: str | None = Field(
        default=None, description="Base RPC URL"
    )
    optimism_rpc_url: str | None = Field(
        default=None, description="Optimism RPC URL"
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./liquidation_alerter.db",
        description="Database connection URL",
    )
    monitoring_interval_seconds: int = Field(
        default=60, description="Interval between monitoring cycles"
    )
    health_factor_threshold: float = Field(
        default=1.5, description="Health factor threshold for warnings"
    )
    critical_health_factor_threshold: float = Field(
        default=1.1, description="Critical health factor threshold for urgent alerts"
    )
    metrics_port: int = Field(
        default=8080, description="Port for Prometheus metrics endpoint"
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
