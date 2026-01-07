# The Castle (MVP) — Kalshi Paper/Demo Trading Research Bot

This repository is an **MVP research scaffold** for:
- Ingesting Kalshi market data from demo or production environments
- Optionally ingesting news (RSS, NewsAPI.org)
- Generating features and trading signals
- Executing in multiple modes: test, paper, training, demo, or prod
- Producing detailed run artifacts with diagnostics for iterative improvement

> ⚠️ **Not financial advice.** Use **test/paper/training modes first** and comply with Kalshi rules and your local laws.

## Quick Start

### 1) Create a venv and install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### 2) Configure environment
Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
# Edit .env with your preferred editor
```

**Key settings:**
- `KALSHI_ENV`: `demo` or `prod` (controls which API endpoint to use)
- `CASTLE_MODE`: `test`, `paper`, `training`, `demo`, or `prod` (controls execution behavior)
- API credentials only needed for `demo`/`prod` modes

### 3) Initialize DB
```bash
castle init-db-cmd
```

### 4) Run in paper mode (default, safe)
```bash
castle run --minutes 5
```

### 5) Review results
```bash
# Get the latest run ID
RUN_ID=$(ls -1t runs | head -n1)

# View detailed report
castle report $RUN_ID

# View logs
cat runs/$RUN_ID/logs.txt

# View diagnostics in summary.json
cat runs/$RUN_ID/summary.json | jq .diagnostics
```

## Trading Modes Explained

The Castle supports **5 distinct modes** that control execution behavior independently from the data source:

### 🧪 Test Mode (`CASTLE_MODE=test`)
- **Purpose:** Validate API connectivity and data ingestion
- **Requirements:** `KALSHI_ENV=demo`, API credentials
- **Behavior:** Fetches data, generates decisions, but **never places orders**
- **Use case:** Verify your API setup works before any trading

```bash
# Set in .env:
# KALSHI_ENV=demo
# CASTLE_MODE=test
castle run --minutes 5 --mode test
```

### 📝 Paper Mode (`CASTLE_MODE=paper`, default)
- **Purpose:** Backtest strategy with simulated fills
- **Requirements:** None (can use demo or prod data)
- **Behavior:** Simulates conservative fills based on orderbook state
- **Use case:** Test strategy logic without any risk

```bash
# Works with any KALSHI_ENV
castle run --minutes 5 --mode paper
```

### 🎓 Training Mode (`CASTLE_MODE=training`) ⭐ NEW
- **Purpose:** Use **production market data** without trading
- **Requirements:** `KALSHI_ENV=prod`, API credentials (read-only)
- **Behavior:** 
  - Fetches real production markets and orderbooks
  - Generates decisions based on live data
  - Logs "would trade" entries to `would_trade.csv`
  - **Never places orders** (enforced at code level)
- **Use case:** Validate strategy on real markets safely before going live

```bash
# Set in .env:
# KALSHI_ENV=prod
# CASTLE_MODE=training
# KALSHI_API_KEY_ID=your_key
# KALSHI_PRIVATE_KEY_PATH=path/to/key.pem

castle run --minutes 10 --mode training
```

**Safety guarantees:**
- Training mode **cannot** place orders (executor is not initialized)
- "Would trade" entries are logged separately from actual trades
- All production data is safely used for observation only

### 🧪 Demo Trading Mode (`CASTLE_MODE=demo`)
- **Purpose:** Place real orders in Kalshi's demo environment
- **Requirements:** `KALSHI_ENV=demo`, API credentials
- **Behavior:** Submits actual limit orders to demo API
- **Use case:** End-to-end execution testing in safe environment

```bash
# Requires confirmation prompt
castle run --minutes 5 --mode demo
```

### 🚨 Production Trading Mode (`CASTLE_MODE=prod`)
- **Purpose:** Place real orders with real money
- **Requirements:** `KALSHI_ENV=prod`, API credentials
- **Behavior:** Submits actual limit orders to production API
- **Use case:** Live trading (only after extensive testing!)

```bash
# Requires confirmation prompt + thorough testing
castle run --minutes 5 --mode prod
```

## Diagnostics & Observability

Every run now produces comprehensive diagnostics to help understand why decisions are/aren't being made:

### Diagnostic Counters

```json
{
  "markets_fetched": 50,
  "markets_with_orderbooks": 30,
  "markets_empty_orderbook": 15,
  "markets_no_best_prices": 3,
  "markets_spread_too_wide": 8,
  "markets_insufficient_depth": 4,
  "markets_insufficient_edge": 5,
  "decisions_generated": 3,
  "orders_attempted": 3,
  "trades_filled_paper": 1
}
```

### Skip Reasons

The strategy now logs **why** each market was skipped:

- `empty_orderbook`: No bids on either side
- `no_best_prices`: Cannot compute bid/ask
- `spread_too_wide`: Bid-ask spread exceeds `MAX_SPREAD_CENTS`
- `insufficient_depth`: Not enough contracts within 5¢ of best price
- `insufficient_edge`: Model edge below `MIN_EDGE_PROB`
- `max_exposure_reached`: Total exposure at limit

View skip reasons in logs or `summary.json`:

```bash
cat runs/$RUN_ID/logs.txt | grep "Skip"
jq .diagnostics.skip_reasons_sample runs/$RUN_ID/summary.json
```

## Configuration Guide

### Strategy Parameters

```bash
# Risk limits (USD)
BANKROLL_USD=500
MAX_RISK_PER_MARKET_USD=20
MAX_TOTAL_EXPOSURE_USD=100

# Market quality filters
MIN_EDGE_PROB=0.03              # Minimum 3% edge required
MAX_SPREAD_CENTS=10             # Max 10¢ bid-ask spread
MIN_DEPTH_CONTRACTS=50          # Min 50 contracts within 5¢

# Order type
MAKER_ONLY=true                 # Only place resting limit orders

# Testing overrides
ENABLE_TAKER_TEST=false         # Test taker logic in paper/training mode
```

### Improving Performance

If you're getting **0 decisions**, try these adjustments:

1. **Increase market coverage:**
   ```bash
   castle run --minutes 5 --limit-markets 200
   ```

2. **Relax filters temporarily:**
   ```bash
   # In .env:
   MIN_EDGE_PROB=0.01           # Lower from 0.03
   MAX_SPREAD_CENTS=20          # Raise from 10
   MIN_DEPTH_CONTRACTS=20       # Lower from 50
   ```

3. **Test taker logic:**
   ```bash
   # In .env:
   ENABLE_TAKER_TEST=true
   ```
   This lets you test crossing the spread even when `MAKER_ONLY=true`

4. **Use training mode with prod data:**
   Production markets tend to have better liquidity than demo markets

## Commands

### Core Commands

```bash
# Initialize database
castle init-db-cmd

# Run trading loop
castle run --minutes 10 [--mode MODE] [--limit-markets N]

# View run report
castle report RUN_ID

# Bundle artifacts for sharing
castle bundle RUN_ID

# Evaluate metrics
castle eval RUN_ID
```

### Improvement Workflow

```bash
# Generate improvement proposal from run metrics
castle improve propose --run-id RUN_ID

# Review proposed changes
ls proposals/PROPOSAL_ID/files/

# Apply proposal (with safety checks)
castle improve apply --proposal-id PROPOSAL_ID

# Full cycle (run → eval → propose)
castle improve cycle --minutes 10
```

## Run Artifacts

Each run produces:

```
runs/YYYYMMDDTHHMMSSZ/
├── logs.txt                 # Detailed execution logs
├── summary.json             # Run metadata + diagnostics
├── config.redacted.json     # Configuration (secrets redacted)
├── decisions.csv            # All trading decisions
├── trades.csv               # Executed trades
├── equity.csv               # Portfolio snapshots
├── would_trade.csv          # (training mode only)
├── run_summary.txt          # Human-readable summary
└── prices_end.json          # Final market prices
```

### Key Files

- **summary.json**: Contains `diagnostics` object with skip reasons and counters
- **decisions.csv**: Shows all generated decisions (even if not executed)
- **would_trade.csv**: (Training mode) Shows what would have been traded
- **logs.txt**: Full execution log with skip reasons and diagnostic info

## Testing

### Run Tests

```bash
# Install pytest (optional dependency)
pip install pytest

# Run all tests
pytest

# Run specific test file
pytest tests/test_diagnostics_and_modes.py

# Verbose output
pytest -v
```

### Test Coverage

- `test_orderbook_math.py`: Orderbook calculations
- `test_diagnostics_and_modes.py`: Mode validation and diagnostics
- `test_strategy_skip_reasons.py`: Strategy skip logic

## Security & Safety

### Never Commit Secrets

- Keep API keys in `.env` (gitignored)
- Never commit `.env` or `secrets/` directory
- If you accidentally expose keys, **rotate them immediately**

### Mode Safety

The code enforces safety at multiple levels:

1. **Configuration validation**: Invalid mode combinations fail at startup
2. **Executor gating**: Training mode never initializes live executor
3. **Confirmation prompts**: Demo/prod modes require explicit confirmation

### Production Checklist

Before using `prod` mode:

- [ ] Thoroughly tested in `test` mode
- [ ] Validated strategy in `paper` mode
- [ ] Observed real markets in `training` mode
- [ ] Tested execution in `demo` mode
- [ ] Reviewed and understand all risk parameters
- [ ] Confirmed compliance with Kalshi ToS
- [ ] Set appropriate position limits

## Troubleshooting

### No decisions generated?

Check diagnostics:
```bash
cat runs/$RUN_ID/summary.json | jq .diagnostics
```

Common issues:
- Empty orderbooks (`markets_empty_orderbook`)
- Spreads too wide (`markets_spread_too_wide`)
- Insufficient edge (`markets_insufficient_edge`)

### Training mode not working?

Ensure:
```bash
# In .env:
KALSHI_ENV=prod
CASTLE_MODE=training
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem
```

### Tests failing?

```bash
# Ensure pytest is installed
pip install pytest

# Check pytest configuration
cat pytest.ini
```

## Self-Improvement Loop

The Castle includes a **spec-driven improvement system** that can propose code changes based on run metrics:

### Workflow

1. **Run** a session (any mode)
2. **Evaluate** the run metrics
3. **Propose** improvements using LLM (Gemini or OpenAI)
4. **Review** proposed changes
5. **Apply** if acceptable
6. **Iterate**

### Setup for Improvements

```bash
# Option 1: OpenAI (recommended)
# In .env:
CODEGEN_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.2

# Option 2: Gemini
CODEGEN_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

### Example Improvement Cycle

```bash
# Run a session
castle run --minutes 10

# Get latest run
RUN_ID=$(ls -1t runs | head -n1)

# Generate improvement proposal
castle improve propose --run-id $RUN_ID

# Review proposed files
PROPOSAL_ID=$(ls -1t proposals | head -n1)
ls -la proposals/$PROPOSAL_ID/files/

# Apply if acceptable
castle improve apply --proposal-id $PROPOSAL_ID
```

### What Gets Proposed

The improvement system can suggest:
- Strategy tweaks based on skip reasons
- Better market selection logic
- Feature engineering improvements
- Risk management adjustments
- Diagnostic improvements

**Important:** Proposals are never applied automatically. Always review before applying.

## Repository Structure

```
castle-bot/
├── src/castle/              # Main package
│   ├── cli.py              # Command-line interface
│   ├── config.py           # Settings and validation
│   ├── diagnostics.py      # Run diagnostics tracking
│   ├── runner.py           # Main trading loop
│   ├── db.py               # Database utilities
│   ├── models.py           # SQLAlchemy models
│   ├── kalshi/             # Kalshi API client
│   ├── strategy/           # Trading strategy
│   ├── execution/          # Order execution
│   ├── news/               # News ingestion
│   ├── improve/            # Improvement system
│   └── llm/                # LLM clients
├── tests/                   # Unit tests
├── minions/                # Requirements spec
├── runs/                   # Run artifacts (gitignored)
├── proposals/              # Improvement proposals (gitignored)
├── .env                    # Configuration (gitignored)
├── .env.example            # Configuration template
├── pytest.ini              # Pytest configuration
└── README.md               # This file
```

## FAQ

### Q: What's the difference between KALSHI_ENV and CASTLE_MODE?

**KALSHI_ENV** controls the data source:
- `demo`: Use Kalshi demo API
- `prod`: Use Kalshi production API

**CASTLE_MODE** controls execution behavior:
- `test`, `paper`, `training`: No trading
- `demo`, `prod`: Place real orders

They're independent! You can use prod data without trading via `training` mode.

### Q: Is training mode safe?

Yes! Training mode:
- Never initializes the live executor
- Cannot place orders (code-level enforcement)
- Only uses read-only API calls
- Logs all decisions to `would_trade.csv`

### Q: Why am I getting 0 trades in paper mode?

Paper mode is **intentionally conservative** for maker orders. If `MAKER_ONLY=true`:
- Resting orders don't fill immediately
- You see decisions but no fills

Try:
1. Set `ENABLE_TAKER_TEST=true` to test crossing the spread
2. Run longer (`--minutes 30`)
3. Use `training` mode to see what real markets look like

### Q: Can I use this for actual trading?

This is a **research scaffold**, not production trading software. If you choose to trade:
- Start with demo mode
- Understand all risks
- Follow Kalshi's ToS
- Use appropriate position limits
- Monitor actively

### Q: How do I contribute improvements?

1. Test your changes in paper mode
2. Add unit tests
3. Run `pytest` to verify
4. Submit changes via the improvement system or manual patches

## License

MIT

## Disclaimer

This software is for research and educational purposes. Trading involves substantial risk of loss. Past performance does not guarantee future results. The authors are not responsible for any trading losses.

Always comply with applicable laws and exchange rules. Consult appropriate professionals before trading.
