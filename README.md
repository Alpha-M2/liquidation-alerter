# DeFi Liquidation Alerter

A production-grade Python application that monitors user positions across multiple DeFi lending protocols on Ethereum and sends proactive Telegram alerts before liquidations occur. Built for reliability, extensibility, and real-time responsiveness.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Supported Protocols](#supported-protocols)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Bot Commands](#bot-commands)
- [Health Factor System](#health-factor-system)
- [Price Oracle System](#price-oracle-system)
- [Alerting System](#alerting-system)
- [Analytics & Simulation](#analytics--simulation)
- [Cascade Detection](#cascade-detection)
- [Prometheus Metrics](#prometheus-metrics)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Development](#development)
- [License](#license)

---

## Overview

DeFi lending protocols like Aave, Compound, and MakerDAO allow users to deposit collateral and borrow assets. If the value of collateral drops below a certain threshold (determined by the **health factor**), the position becomes eligible for **liquidation**, where a third party can repay part of the debt and seize collateral at a discount.

This application helps users avoid liquidation by:

1. **Monitoring** wallet positions across multiple protocols in real-time
2. **Alerting** users via Telegram when health factors approach dangerous levels
3. **Simulating** the impact of price changes on positions
4. **Detecting** systemic risks like liquidation cascades

---

## Features

### Core Monitoring
- **Multi-Protocol Support**: Monitor positions on 6 major DeFi protocols simultaneously
- **Real-Time Health Tracking**: Continuous monitoring with configurable intervals (default: 60 seconds)
- **Unified Health Score**: Cross-protocol normalized risk score (0-100) for portfolio-level view
- **Position Snapshots**: Historical tracking of health factors, collateral, and debt values

### Smart Alerting
- **Tiered Alerts**: Warning, Critical, and Liquidatable status levels
- **Customizable Thresholds**: Per-user configurable alert thresholds
- **Rapid Deterioration Detection**: Alerts when health factor drops >10% within 1 hour
- **Gas-Aware Recommendations**: Considers current gas costs when suggesting actions
- **Smart Cooldowns**: Prevents alert fatigue with status-based cooldown periods

### Analytics
- **Price Impact Simulation**: "What-if" scenarios for collateral price changes
- **Stress Testing**: Automated simulations at -5%, -10%, -20%, -30%, -40%, -50%
- **Liquidation Prediction**: Risk level assessment and estimated time to liquidation
- **Historical Analysis**: Track average, min, max health factors over time

### Operations
- **Prometheus Metrics**: Full observability with 20+ metrics
- **Health Endpoint**: `/health` for load balancer health checks
- **Graceful Shutdown**: Proper cleanup on SIGINT/SIGTERM
- **Rate Limiting**: Built-in RPC rate limiting to respect provider limits
- **Fallback RPC**: Automatic failover between multiple RPC endpoints

---

## Supported Protocols

| Protocol | Version | Network | Contract Address |
|----------|---------|---------|------------------|
| Aave | V3 | Ethereum Mainnet | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` |
| Aave | V2 | Ethereum Mainnet | `0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9` |
| Compound | V3 | Ethereum Mainnet | `0xc3d688B66703497DAA19211EEdff47f25384cdc3` |
| Compound | V2 | Ethereum Mainnet | `0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B` |
| MakerDAO | Vaults | Ethereum Mainnet | Multiple (CDP Manager) |
| Morpho | Blue | Ethereum Mainnet | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` |

---

## Architecture

```
liquidation-alerter/
├── app/
│   ├── main.py                 # Application entry point, lifecycle management
│   ├── config.py               # Pydantic settings with environment variable support
│   ├── database.py             # SQLAlchemy async ORM models and database management
│   │
│   ├── core/
│   │   ├── engine.py           # Main monitoring loop, orchestrates all checks
│   │   ├── health.py           # Health factor calculations, unified scoring
│   │   ├── alerter.py          # Gas-aware alerting with cooldowns and rate limiting
│   │   ├── analytics.py        # Price simulation and liquidation prediction
│   │   └── cascade.py          # Systemic risk and cascade detection
│   │
│   ├── protocols/
│   │   ├── base.py             # Abstract ProtocolAdapter interface
│   │   ├── aave_v3.py          # Aave V3 Pool contract integration
│   │   ├── aave_v2.py          # Aave V2 LendingPool integration
│   │   ├── compound_v3.py      # Compound V3 (Comet) integration
│   │   ├── compound_v2.py      # Compound V2 Comptroller integration
│   │   ├── maker.py            # MakerDAO CDP/Vault integration
│   │   └── morpho.py           # Morpho Blue integration
│   │
│   ├── services/
│   │   ├── rpc.py              # Fallback Web3 provider with rate limiting
│   │   ├── price.py            # Multi-source price service orchestrator
│   │   ├── chainlink.py        # Chainlink oracle integration (primary)
│   │   ├── uniswap_oracle.py   # Uniswap V3 TWAP oracle (fallback)
│   │   └── metrics.py          # Prometheus metrics collection
│   │
│   └── bot/
│       ├── handler.py          # Telegram command handlers
│       └── messages.py         # Message formatting and templates
│
├── tests/                      # Test suite
├── pyproject.toml              # Project dependencies and metadata
└── README.md
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Telegram Bot                                │
│  /add  /remove  /status  /simulate  /pause  /resume  /export  /history  │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Monitoring Engine                               │
│  • Periodic position checks       • Cascade detection                    │
│  • Gas price fetching             • User preference handling             │
└─────────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Protocol        │  │ Price Service   │  │ Alerter         │
│ Adapters        │  │                 │  │                 │
│                 │  │ • Chainlink     │  │ • Cooldowns     │
│ • Aave V2/V3    │  │ • Uniswap TWAP  │  │ • Gas awareness │
│ • Compound V2/3 │  │ • CoinGecko     │  │ • Deterioration │
│ • MakerDAO      │  │                 │  │   detection     │
│ • Morpho        │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                    │
          ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Fallback RPC Provider                               │
│  • Multiple endpoints   • Rate limiting   • Automatic failover           │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                          ┌─────────────────┐
                          │  Ethereum Node  │
                          │   (RPC)         │
                          └─────────────────┘
```

---

## Installation

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Ethereum RPC endpoint (Alchemy, Infura, QuickNode, etc.)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/liquidation-alerter.git
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
  -e RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your_key \
  -p 8080:8080 \
  liquidation-alerter

# Or use docker-compose
docker-compose up -d
```

---

## Configuration

All configuration is done via environment variables (or a `.env` file):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Telegram Bot API token from @BotFather |
| `RPC_URL` | Yes | - | Ethereum JSON-RPC endpoint URL |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./liquidation_alerter.db` | Database connection string |
| `MONITORING_INTERVAL_SECONDS` | No | `60` | Seconds between monitoring cycles |
| `HEALTH_FACTOR_THRESHOLD` | No | `1.5` | Default warning threshold |
| `CRITICAL_HEALTH_FACTOR_THRESHOLD` | No | `1.1` | Default critical threshold |
| `METRICS_PORT` | No | `8080` | Port for Prometheus metrics endpoint |

### Example `.env` file

```env
# Required
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your-api-key

# Optional
DATABASE_URL=sqlite+aiosqlite:///./liquidation_alerter.db
MONITORING_INTERVAL_SECONDS=60
HEALTH_FACTOR_THRESHOLD=1.5
CRITICAL_HEALTH_FACTOR_THRESHOLD=1.1
METRICS_PORT=8080
```

---

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Initialize bot and show welcome message | `/start` |
| `/help` | Show available commands | `/help` |
| `/add <address>` | Add a wallet to monitor | `/add 0x1234...abcd` |
| `/remove <address>` | Remove a wallet from monitoring | `/remove 0x1234...abcd` |
| `/status` | View current positions and health factors | `/status` |
| `/simulate [%]` | Simulate price impact on positions | `/simulate -20` |
| `/set_threshold <value>` | Set personal alert threshold (1.0-5.0) | `/set_threshold 1.3` |
| `/pause` | Pause all alerts | `/pause` |
| `/resume` | Resume alerts | `/resume` |
| `/protocols` | List supported protocols with links | `/protocols` |
| `/export` | Download position history as CSV | `/export` |
| `/history` | View historical health factor analysis | `/history` |

---

## Health Factor System

### Understanding Health Factor

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

### Unified Health Score

For users with positions on multiple protocols, the system calculates a **Unified Health Score** (0-100):

- **Score Calculation**: Based on the worst (lowest) health factor across all positions
- **Weighted Average**: Considers debt amounts for overall portfolio view
- **Protocol Breakdown**: Shows individual health factors per protocol

### Action Recommendations

When health factor is low, the system calculates exact amounts needed:

1. **Repay Debt**: How much to repay to reach target HF
2. **Add Collateral**: How much collateral to deposit

```
Repayment for HF 1.5 = Current Debt - (Collateral × Threshold / 1.5)
Deposit for HF 1.5 = (1.5 × Debt / Threshold) - Current Collateral
```

---

## Price Oracle System

The application uses a multi-source price oracle with automatic fallback:

### Priority Order

1. **Chainlink (Primary)** - Highest confidence (95%)
   - On-chain price feeds
   - Staleness detection (>1 hour = stale)
   - Deviation checks against secondary sources

2. **Uniswap V3 TWAP (Secondary)** - Medium confidence (70-85%)
   - Time-Weighted Average Price over configurable window
   - DEX-based, manipulation-resistant
   - Used when Chainlink is stale or unavailable

3. **CoinGecko API (Fallback)** - Lower confidence (75%)
   - Off-chain aggregated prices
   - Used as last resort

### Supported Tokens

ETH, WETH, USDC, USDT, DAI, WBTC, LINK, UNI, AAVE, CRV, MKR, SNX, COMP, YFI, SUSHI, BAL, 1INCH, ENS, LDO, RPL, cbETH, rETH, stETH, wstETH

### Price Validation

- Maximum 5% deviation allowed between sources
- Automatic logging of significant deviations
- Cache TTL: 30 seconds for performance

---

## Alerting System

### Alert Types

1. **Warning Alert** (HF < 1.5)
   - Yellow indicator
   - Recommendations to add collateral

2. **Critical Alert** (HF < 1.1)
   - Red indicator
   - Urgent action required

3. **Liquidation Alert** (HF ≤ 1.0)
   - Skull indicator
   - Position is liquidatable

4. **Rapid Deterioration Alert**
   - Triggered when HF drops >10% in 1 hour
   - Even applies to healthy positions

5. **Cascade Alert**
   - Systemic risk warning
   - Multiple liquidations detected on protocol

### Cooldown Periods

To prevent alert fatigue:

| Status | Cooldown |
|--------|----------|
| Liquidatable | 5 minutes |
| Critical | 15 minutes |
| Warning | 1 hour |
| Healthy | 24 hours |

### Gas-Aware Alerting

The system considers current gas costs:
- Estimates transaction cost (~200k gas units)
- Compares to position value
- Warns if gas > 5% of position value
- Still alerts for critical positions regardless

---

## Analytics & Simulation

### Price Impact Simulation

Simulate how price changes affect your positions:

```
/simulate -20
```

This calculates:
- New health factor at -20% collateral price
- Whether position would be liquidated
- Collateral at risk

### Stress Testing

Automatic stress test with multiple scenarios:
- -5%, -10%, -15%, -20%, -25%, -30%, -40%, -50%

### Liquidation Prediction

Based on required price drop:

| Price Drop to Liquidation | Risk Level | Estimated Timeframe |
|---------------------------|------------|---------------------|
| ≤ 5% | Extreme | Hours |
| 5-10% | Very High | Days |
| 10-20% | High | Weeks |
| 20-30% | Moderate | Months |
| > 30% | Low | Very unlikely |

---

## Cascade Detection

### What is a Liquidation Cascade?

A cascade occurs when multiple positions are liquidated in rapid succession, often due to:
- Sharp price drops
- Overleveraged positions with similar collateral
- Systemic protocol risk

### Detection Thresholds

| Severity | Liquidations (1 hour) | Value (1 hour) |
|----------|----------------------|----------------|
| Warning | 5+ | $1M+ |
| Critical | 10+ | $5M+ |
| Severe | 20+ | $10M+ |

### Monitored Events

- Aave V2/V3: `LiquidationCall` events
- Compound V2: `LiquidateBorrow` events

---

## Prometheus Metrics

Metrics are exposed at `http://localhost:8080/metrics`

### Available Metrics

**RPC Metrics**
- `defi_alerter_rpc_requests_total` - Total RPC requests by endpoint/method/status
- `defi_alerter_rpc_request_duration_seconds` - RPC latency histogram
- `defi_alerter_rpc_errors_total` - RPC errors by type

**Position Metrics**
- `defi_alerter_positions_checked_total` - Positions checked by protocol
- `defi_alerter_position_health_factor` - Current HF per wallet/protocol
- `defi_alerter_position_collateral_usd` - Collateral value
- `defi_alerter_position_debt_usd` - Debt value

**Alert Metrics**
- `defi_alerter_alerts_sent_total` - Alerts sent by protocol/severity
- `defi_alerter_alerts_failed_total` - Failed alerts

**Oracle Metrics**
- `defi_alerter_oracle_requests_total` - Oracle requests by source/symbol
- `defi_alerter_oracle_price_usd` - Current prices
- `defi_alerter_oracle_staleness_seconds` - Price age

**Cascade Metrics**
- `defi_alerter_liquidations_detected_total` - Detected liquidations
- `defi_alerter_liquidation_value_usd_total` - Total liquidation value
- `defi_alerter_cascade_alerts_total` - Cascade alerts sent

**System Metrics**
- `defi_alerter_gas_price_gwei` - Current gas price
- `defi_alerter_active_users` - Active user count
- `defi_alerter_monitored_wallets` - Monitored wallet count
- `defi_alerter_monitoring_cycle_duration_seconds` - Cycle duration

### Health Endpoint

```bash
curl http://localhost:8080/health
# {"status": "healthy"}
```

---

## Database Schema

### Users Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| chat_id | BigInteger | Telegram chat ID (unique) |
| alert_threshold | Float | Custom warning threshold (default: 1.5) |
| critical_threshold | Float | Custom critical threshold (default: 1.1) |
| alerts_paused | Boolean | Whether alerts are paused |
| created_at | DateTime | Account creation time |

### Wallets Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | Integer | Foreign key to users |
| address | String(42) | Ethereum address |
| label | String(100) | Optional label |
| created_at | DateTime | When wallet was added |

### Position Snapshots Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| wallet_id | Integer | Foreign key to wallets |
| protocol | String(50) | Protocol name |
| health_factor | Float | Health factor at snapshot |
| total_collateral_usd | Float | Collateral value |
| total_debt_usd | Float | Debt value |
| timestamp | DateTime | Snapshot time |

---

## API Reference

### Protocol Adapter Interface

All protocol adapters implement the `ProtocolAdapter` abstract base class:

```python
class ProtocolAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Protocol display name"""
        pass

    @abstractmethod
    async def get_position(self, wallet_address: str) -> Position | None:
        """Get full position data for a wallet"""
        pass

    @abstractmethod
    async def get_health_factor(self, wallet_address: str) -> float | None:
        """Get just the health factor"""
        pass

    @abstractmethod
    async def has_position(self, wallet_address: str) -> bool:
        """Check if wallet has an active position"""
        pass
```

### Position Data Structure

```python
@dataclass
class Position:
    protocol: str              # e.g., "Aave V3"
    wallet_address: str        # Ethereum address
    health_factor: float       # Current HF
    collateral_assets: List[Asset]  # Collateral breakdown
    debt_assets: List[Asset]        # Debt breakdown
    total_collateral_usd: float
    total_debt_usd: float
    liquidation_threshold: float    # e.g., 0.825 for 82.5%
    available_borrows_usd: float
```

---

## Development

### Running Tests

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
pytest

# Run with coverage
pytest --cov=app
```

### Adding a New Protocol

1. Create new adapter in `app/protocols/`:

```python
from app.protocols.base import ProtocolAdapter, Position

class NewProtocolAdapter(ProtocolAdapter):
    @property
    def name(self) -> str:
        return "New Protocol"

    async def get_position(self, wallet_address: str) -> Position | None:
        # Implement contract calls
        pass
```

2. Register in `app/core/engine.py`:

```python
self._adapters: List[ProtocolAdapter] = [
    AaveV3Adapter(),
    # ... existing adapters
    NewProtocolAdapter(),  # Add here
]
```

### Code Style

- Python 3.11+ with type hints
- Async/await for all I/O operations
- Pydantic for settings validation
- SQLAlchemy 2.0 async ORM

---

## License

MIT License - See LICENSE file for details.

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Submit a pull request

---

## Support

- Open an issue on GitHub for bugs or feature requests
- For security vulnerabilities, please email directly

---

Built with care for the DeFi community.
