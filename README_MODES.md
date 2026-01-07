# README.md - Mode Documentation Section Addition

## Execution Modes

The Castle supports multiple execution modes to separate data sources from trading behavior:

### Environment (`KALSHI_ENV`)
Controls **where data comes from**:
- `demo`: Kalshi demo API (safe for testing)
- `prod`: Kalshi production API (real markets)

### Mode (`CASTLE_MODE`)
Controls **what happens with that data**:

| Mode | Data Source | Trading | Use Case |
|------|-------------|---------|----------|
| `test` | Demo | No | API validation, integration testing |
| `paper` | Demo or Prod | No (simulated) | Strategy backtesting |
| `training` | **Prod** | **No** | Research on real markets without risk |
| `demo` | Demo | **Yes** | Test trading with demo account |
| `prod` | Prod | **Yes** | **REAL TRADING** |

### Training Mode (Recommended for Research)

Training mode is designed for safe research on production market data:

```bash
# .env configuration
KALSHI_ENV=prod              # Use real market data
CASTLE_MODE=training         # But DON'T place orders
ALLOW_TAKER_IN_PAPER=true   # Enable taker testing

# Run it
castle run --minutes 10 --mode training
```

**What training mode does:**
- Fetches real orderbooks from production markets
- Generates real trading decisions
- Logs "would place order" entries (never calls order API)
- Produces full run artifacts for analysis
- Safe by construction: execution layer refuses to submit orders

**Output files include:**
- `trades.csv`: Contains "TRAINING_WOULD_PLACE" entries
- `decisions.csv`: All trading decisions that would have been made
- `skips.csv`: Markets that were filtered out (with reasons)
- `diagnostics.json`: Counters for markets seen, decisions, etc.

### Safety Guardrails

1. **Prod mode requires explicit confirmation:**
   ```bash
   castle run --mode prod
   # Prompts: "Are you absolutely sure you want to trade in PROD mode?"
   ```

2. **Training mode can't accidentally trade:**
   - Uses `TrainingExecutor` which has no order submission code
   - Even with credentials, cannot place orders

3. **Mode validation:**
   - Invalid modes are rejected at CLI
   - Mismatched env/mode combinations warn users

## Diagnostics

Every run now produces detailed diagnostics:

```bash
castle run --minutes 5
# Shows:
#   Markets seen: 40
#   With orderbooks: 35
#   Decisions generated: 5
#   Trades filled: 2
#   
#   Top skip reasons:
#     spread_too_wide: 15
#     insufficient_depth: 10
#     edge_too_small: 8
```

Skip reasons help you understand why markets were filtered:
- `no_prices`: Empty orderbook
- `spread_too_wide`: Bid-ask spread exceeds max
- `insufficient_depth`: Not enough liquidity
- `edge_too_small`: Insufficient edge vs threshold
- `max_exposure_reached`: Risk limits hit

Files created:
- `diagnostics.json`: Full diagnostic counters
- `skips.csv`: Per-market skip reasons with details

## Example Workflows

### Safe Research on Real Markets
```bash
# Step 1: Configure for training
export KALSHI_ENV=prod
export CASTLE_MODE=training
export ALLOW_TAKER_IN_PAPER=true

# Step 2: Run
castle run --minutes 30

# Step 3: Analyze
castle report <run_id>
castle eval <run_id>

# Step 4: Bundle and share
castle bundle <run_id>
```

### Paper Trading Strategy Development
```bash
export KALSHI_ENV=demo  # or prod for real data
export CASTLE_MODE=paper

castle run --minutes 10
```

### Demo Environment Validation
```bash
export KALSHI_ENV=demo
export CASTLE_MODE=demo  # Actually places demo orders

castle run --minutes 5
```

### Production Trading (Careful!)
```bash
export KALSHI_ENV=prod
export CASTLE_MODE=prod

castle run --minutes 5
# Requires explicit confirmation
```
