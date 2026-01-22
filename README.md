# DeFi Liquidation Alerter

A production-grade Python application that monitors user positions across Aave V3 and Compound V3 on multiple EVM chains and sends proactive Telegram alerts before liquidations occur.

## Overview

DeFi lending protocols allow users to deposit collateral and borrow assets. If the value of collateral drops below a certain threshold (determined by the **health factor**), the position becomes eligible for **liquidation**.

This application helps users avoid liquidation by:

1. **Monitoring** wallet positions across multiple protocols and chains in real-time
2. **Alerting** users via Telegram when health factors approach dangerous levels
3. **Simulating** the impact of price changes on positions
4. **Detecting** systemic risks like liquidation cascades
5. **Displaying** detailed per-asset breakdowns with APYs and risk parameters

## Supported Protocols & Chains

| Protocol | Chain | Contract Address |
|----------|-------|------------------|
| Aave V3 | Ethereum | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` |
| Aave V3 | Arbitrum | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` |
| Aave V3 | Base | `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5` |
| Aave V3 | Optimism | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` |
| Compound V3 | Ethereum | `0xc3d688B66703497DAA19211EEdff47f25384cdc3` |
| Compound V3 | Arbitrum | `0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf` |
| Compound V3 | Base | `0xb125E6687d4313864e53df431d5425969c15Eb2F` |
| Compound V3 | Optimism | `0x2e44e174f7D53F0212823acC11C01A11d58c5bCB` |

## Features

### Core Monitoring
- **Multi-Chain Support**: Monitor positions on Ethereum, Arbitrum, Base, and Optimism
- **Multi-Protocol Support**: Aave V3 and Compound V3 integration
- **Real-Time Health Tracking**: Continuous monitoring with configurable intervals (default: 60 seconds)
- **Unified Health Score**: Cross-protocol normalized risk score for portfolio-level view
- **Position Snapshots**: Historical tracking of health factors, collateral, and debt values

### Detailed Position Display
- **Per-Asset Breakdown**: View individual collateral and debt assets with balances
- **Token Amounts**: See exact token quantities (e.g., "3.45 WETH") alongside USD values
- **APY Information**: Supply and borrow APYs for each asset
- **Risk Parameters**: LTV ratios and liquidation thresholds per collateral asset
- **Net APY Calculation**: Overall position yield after accounting for borrow costs
- **Token Recognition**: Visual emoji indicators for 40+ common DeFi tokens

### Smart Alerting
- **Tiered Alerts**: Warning, Critical, and Liquidatable status levels
- **Customizable Thresholds**: Per-user configurable alert thresholds
- **Rapid Deterioration Detection**: Alerts when health factor drops >10% within 1 hour
- **Gas-Aware Recommendations**: Considers current gas costs when suggesting actions
- **Smart Cooldowns**: Prevents alert fatigue with status-based cooldown periods

### Analytics
- **Price Impact Simulation**: "What-if" scenarios for collateral price changes
- **Stress Testing**: Automated simulations at various price drop levels
- **Liquidation Prediction**: Risk level assessment and estimated time to liquidation
- **Historical Analysis**: Track health factor trends over time

### Performance & Reliability
- **Smart Polling**: Adaptive check intervals based on position risk level
- **Position Caching**: TTL-based caching to reduce RPC calls
- **Reorg Protection**: Confirmation-based state tracking to prevent false alerts
- **Batch Fetching**: Multicall support for efficient on-chain data retrieval

### Operations
- **Prometheus Metrics**: Full observability with comprehensive metrics
- **Health Endpoint**: `/health` for load balancer health checks
- **Graceful Shutdown**: Proper cleanup on SIGINT/SIGTERM
- **Rate Limiting**: Built-in RPC rate limiting to respect provider limits

## Architecture

```
liquidation-alerter/
├── app/
│   ├── main.py                 # Application entry point
│   ├── config.py               # Pydantic settings with chain-specific RPC URLs
│   ├── database.py             # SQLAlchemy async ORM models
│   │
│   ├── core/
│   │   ├── engine.py           # Main monitoring loop with smart polling
│   │   ├── health.py           # Health factor calculations
│   │   ├── alerter.py          # Gas-aware alerting
│   │   ├── analytics.py        # Price simulation and prediction
│   │   └── cascade.py          # Systemic risk detection
│   │
│   ├── protocols/
│   │   ├── base.py             # ProtocolAdapter interface with CollateralAsset/DebtAsset
│   │   ├── aave_v3.py          # Aave V3 adapter with UiPoolDataProvider integration
│   │   └── compound_v3.py      # Compound V3 adapter with per-asset breakdown
│   │
│   ├── services/
│   │   ├── rpc.py              # Fallback Web3 provider with rate limiting
│   │   ├── price.py            # Multi-source price service
│   │   ├── chainlink.py        # Chainlink oracle integration
│   │   ├── uniswap_oracle.py   # Uniswap V3 TWAP oracle
│   │   ├── token_metadata.py   # Token symbol/decimals caching service
│   │   ├── cache.py            # TTL-based position and reserve caching
│   │   ├── multicall.py        # Batch RPC calls for efficiency
│   │   ├── reorg.py            # Chain reorganization protection
│   │   └── metrics.py          # Prometheus metrics
│   │
│   └── bot/
│       ├── handler.py          # Telegram command handlers
│       └── messages.py         # Message formatting with per-asset display
│
├── tests/                      # Test suite (88 tests)
├── pyproject.toml              # Project dependencies
└── README.md
```

## Installation

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- RPC endpoints for the chains you want to monitor

### Quick Start

```bash
# Clone the repository
git clone https://github.com/Alpha-M2/liquidation-alerter.git
cd liquidation-alerter

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run the application
python -m app.main
```

### Docker Deployment

```bash
# Build the image
docker build -t liquidation-alerter .

# Run with environment variables
docker run -d \
  --name liquidation-alerter \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e ETHEREUM_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your_key \
  -e ARBITRUM_RPC_URL=https://arb-mainnet.g.alchemy.com/v2/your_key \
  -e BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/your_key \
  -e OPTIMISM_RPC_URL=https://opt-mainnet.g.alchemy.com/v2/your_key \
  -p 8080:8080 \
  liquidation-alerter
```

### Example `.env` file

```env
# Required
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Chain-specific RPC URLs (ETHEREUM_RPC_URL is required)
ETHEREUM_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your-api-key
ARBITRUM_RPC_URL=https://arb-mainnet.g.alchemy.com/v2/your-api-key
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/your-api-key
OPTIMISM_RPC_URL=https://opt-mainnet.g.alchemy.com/v2/your-api-key

# Optional - Monitoring settings
MONITORING_INTERVAL_SECONDS=60
HEALTH_FACTOR_THRESHOLD=1.5
CRITICAL_HEALTH_FACTOR_THRESHOLD=1.1
```

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Initialize bot and show welcome message | `/start` |
| `/help` | Show available commands | `/help` |
| `/add <address>` | Add a wallet to monitor | `/add 0x1234...abcd` |
| `/remove <address>` | Remove a wallet from monitoring | `/remove 0x1234...abcd` |
| `/status` | View current positions across all chains | `/status` |
| `/detail` | View detailed breakdown with per-asset info | `/detail` |
| `/simulate [%]` | Simulate price impact on positions | `/simulate -20` |
| `/set_threshold <value>` | Set personal alert threshold | `/set_threshold 1.3` |
| `/pause` | Pause all alerts | `/pause` |
| `/resume` | Resume alerts | `/resume` |
| `/protocols` | List supported protocols | `/protocols` |
| `/export` | Download position history as CSV | `/export` |
| `/history` | View historical health factor analysis | `/history` |

## Detailed Position Display

The `/detail` command provides a comprehensive view of your positions:

```
🟢 Aave V3 (Ethereum) | 0x1234...abcd

Health Factor: 2.15 | Status: Healthy
Net APY: +1.24%

📥 Collateral ($45,230.50)
💎 WETH 🔒
   12.5000 WETH ($41,250.00)
   LTV: 80%, Liq: 82.5%, APY: +2.10%
💵 USDC 🔒
   3,980.50 USDC ($3,980.50)
   LTV: 75%, Liq: 80%, APY: +4.50%

📤 Debt ($18,500.00)
💵 USDC 📊
   18,500.00 USDC ($18,500.00)
   Variable, APY: -5.20%

Liq. Threshold: 82% | Available: $12,450.00

Position is healthy with comfortable safety margin.
```

### Asset Information Displayed

| Field | Description |
|-------|-------------|
| Token Balance | Exact amount in native token units |
| USD Value | Current value at market price |
| LTV | Loan-to-Value ratio (max borrow power) |
| Liq. Threshold | Liquidation threshold percentage |
| Supply APY | Interest earned on supplied assets |
| Borrow APY | Interest paid on borrowed assets |
| Net APY | Overall yield after borrow costs |
| Interest Mode | Variable or Stable rate (Aave) |

## Health Factor System

The **Health Factor (HF)** represents the safety of a position:

```
Health Factor = (Total Collateral × Liquidation Threshold) / Total Debt
```

| Health Factor | Status | Risk Level |
|--------------|--------|------------|
| > 2.0 | Healthy | Low |
| 1.5 - 2.0 | Healthy | Moderate |
| 1.1 - 1.5 | Warning | High |
| 1.0 - 1.1 | Critical | Very High |
| ≤ 1.0 | Liquidatable | Imminent |

## Smart Polling

The monitoring engine uses adaptive polling intervals based on position risk:

| Risk Level | Health Factor | Check Interval |
|------------|---------------|----------------|
| Critical | < 1.3 | Every 30 seconds |
| Medium | 1.3 - 2.0 | Every 2 minutes |
| Low | > 2.0 | Every 5 minutes |
| No Position | ∞ | Every 10 minutes |

This ensures high-risk positions are monitored more frequently while reducing RPC costs for safe positions.

## Development

### Running Tests

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_adapters.py -v
```

### Adding a New Chain

To add support for a new chain, update the address dictionaries in the protocol adapters:

```python
# In app/protocols/aave_v3.py
AAVE_V3_POOL_ADDRESSES = {
    "ethereum": "0x...",
    "arbitrum": "0x...",
    "newchain": "0x...",  # Add new chain
}

AAVE_V3_UI_POOL_DATA_PROVIDER = {
    "ethereum": "0x...",
    "arbitrum": "0x...",
    "newchain": "0x...",  # Add UiPoolDataProvider address
}

# In app/protocols/compound_v3.py
COMPOUND_V3_COMET_ADDRESSES = {
    "ethereum": "0x...",
    "arbitrum": "0x...",
    "newchain": "0x...",  # Add new chain
}
```

Then add the chain to the engine's adapter list in `app/core/engine.py` and add the RPC configuration in `app/config.py`.

### Adding Token Metadata

To add recognition for new tokens, update `app/services/token_metadata.py`:

```python
KNOWN_TOKENS = {
    "newchain": {
        "0xTokenAddress": TokenMetadata(
            address="0xTokenAddress",
            symbol="TOKEN",
            decimals=18,
            name="Token Name",
        ),
    },
}
```

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Submit a pull request
