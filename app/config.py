from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from functools import lru_cache
from typing import Self


class Settings(BaseSettings):
    telegram_bot_token: str = Field(..., description="Telegram Bot API token")

    # Chain-specific RPC URLs (ETHEREUM_RPC_URL is required, others use it as fallback)
    ethereum_rpc_url: str = Field(..., description="Ethereum mainnet RPC URL")
    arbitrum_rpc_url: str | None = Field(
        default=None, description="Arbitrum One RPC URL (optional, falls back to ethereum_rpc_url)"
    )
    base_rpc_url: str | None = Field(
        default=None, description="Base RPC URL (optional, falls back to ethereum_rpc_url)"
    )
    optimism_rpc_url: str | None = Field(
        default=None, description="Optimism RPC URL (optional, falls back to ethereum_rpc_url)"
    )

    # Legacy alias for backward compatibility - use ETHEREUM_RPC_URL instead
    rpc_url: str | None = Field(
        default=None, description="[DEPRECATED] Legacy RPC URL, use ETHEREUM_RPC_URL instead"
    )

    @model_validator(mode="after")
    def resolve_rpc_urls(self) -> Self:
        """Resolve RPC URLs with fallback logic."""
        # If legacy rpc_url is set but ethereum_rpc_url wasn't explicitly set,
        # this handles the case where users have old config
        if self.rpc_url and not self.ethereum_rpc_url:
            object.__setattr__(self, "ethereum_rpc_url", self.rpc_url)

        # Set rpc_url to ethereum_rpc_url for backward compatibility with code using rpc_url
        object.__setattr__(self, "rpc_url", self.ethereum_rpc_url)

        return self

    def get_rpc_url(self, chain: str) -> str:
        """Get RPC URL for a specific chain with fallback to ethereum_rpc_url."""
        chain = chain.lower()
        chain_url = getattr(self, f"{chain}_rpc_url", None)
        return chain_url or self.ethereum_rpc_url

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
