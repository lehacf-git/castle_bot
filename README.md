# Castle Bot Improvements Package

## 📦 What's Inside

This package contains comprehensive improvements to the Castle trading bot that add:

- **🎯 Training Mode**: Research on production markets without trading risk
- **📊 Diagnostics System**: Understand why markets are skipped and decisions aren't made
- **🔒 Safety Improvements**: Mode validation and confirmations for prod trading
- **✅ Unit Tests**: Comprehensive tests for new functionality
- **📚 Documentation**: Detailed guides and examples

## 📁 Package Contents

```
castle-improvements/
│
├── install.sh                           # Automated installation script
├── FILE_MANIFEST.md                     # Where each file goes
│
├── Documentation/
│   ├── DEPLOYMENT_GUIDE.md             # Step-by-step installation
│   ├── IMPLEMENTATION_SUMMARY.md        # Technical design details
│   ├── BEFORE_AFTER.md                 # Visual comparison of changes
│   └── README_MODES.md                 # Mode usage guide
│
├── Application Files/
│   ├── src/castle/config.py            # Enhanced config with training mode
│   ├── src/castle/runner.py            # Diagnostics + training support
│   ├── src/castle/cli.py               # Mode validation + confirmations
│   ├── src/castle/strategy/edge_strategy.py  # Skip reason tracking
│   └── src/castle/execution/training.py      # Training mode executor
│
├── Tests/
│   └── tests/test_modes_and_diagnostics.py   # Unit tests
│
└── Config Files/
    ├── .env.example                    # Updated configuration template
    └── pytest.ini                      # Test configuration
```

## 🚀 Quick Start

### Option 1: Automated Installation (Recommended)

```bash
# Extract the package
unzip castle-improvements.zip
cd castle-improvements

# Run the installer (creates backups automatically)
./install.sh /path/to/your/castle-bot
```

### Option 2: Manual Installation

```bash
# See FILE_MANIFEST.md for detailed copy commands
# Example:
cp src/castle/config.py /path/to/castle-bot/src/castle/config.py
cp src/castle/runner.py /path/to/castle-bot/src/castle/runner.py
# ... etc
```

### Verify Installation

```bash
cd /path/to/castle-bot

# Check syntax
python -m compileall src

# Run tests
pip install pytest  # if needed
pytest tests/test_modes_and_diagnostics.py -v

# Quick test run
castle run --minutes 1 --mode paper --limit-markets 5
```

## 🎯 Key Features

### 1. Training Mode

Research on real markets without risk:

```bash
# .env configuration
KALSHI_ENV=prod
CASTLE_MODE=training

# Run it
castle run --minutes 10 --mode training
```

**What it does:**
- ✅ Fetches real production orderbooks
- ✅ Generates real trading decisions  
- ✅ Logs "would place order" entries
- ❌ **Never** calls order submission APIs
- ✅ Produces full run artifacts for analysis

### 2. Diagnostics System

Understand why you're getting 0 trades:

```json
{
  "markets_seen": 40,
  "markets_with_orderbooks": 35,
  "decisions_generated": 5,
  "orders_attempted": 5,
  "trades_filled": 2,
  "skip_reasons": {
    "spread_too_wide": 15,
    "insufficient_depth": 10,
    "edge_too_small": 8
  }
}
```

**New output files:**
- `diagnostics.json` - Aggregate statistics
- `skips.csv` - Per-market skip reasons with details

### 3. Clear Mode Architecture

**Before:** Confusing single mode variable
```bash
CASTLE_MODE=prod  # Does this mean prod data? Prod trading? Both?
```

**After:** Separated concerns
```bash
KALSHI_ENV=prod     # Where to get data: demo | prod
CASTLE_MODE=training # What to do: test | paper | training | demo | prod
```

**All modes:**
- `test` - Demo env, API validation
- `paper` - Simulate fills (default)
- `training` - **Prod data, no trading** ⭐
- `demo` - Place orders in demo
- `prod` - **REAL TRADING** (requires confirmation)

### 4. Safety Features

- Prod mode requires explicit confirmation
- Training mode can't accidentally place orders
- Invalid modes rejected at CLI
- Helpful error messages

## 📖 Documentation

| Document | Purpose |
|----------|---------|
| **DEPLOYMENT_GUIDE.md** | Complete installation walkthrough |
| **FILE_MANIFEST.md** | Where each file should go |
| **IMPLEMENTATION_SUMMARY.md** | Technical design and architecture |
| **BEFORE_AFTER.md** | Visual comparison of changes |
| **README_MODES.md** | Mode usage examples and workflows |

## 🔧 What Changed

### Modified Files (5)
- `src/castle/config.py` - Mode helpers, training mode config
- `src/castle/runner.py` - Diagnostics, training executor integration
- `src/castle/cli.py` - Mode validation, confirmations
- `src/castle/strategy/edge_strategy.py` - Skip reason tracking
- `.env.example` - Updated documentation

### New Files (3)
- `src/castle/execution/training.py` - Training mode executor
- `tests/test_modes_and_diagnostics.py` - Unit tests
- `pytest.ini` - Test configuration

### Changed Behavior
- ✅ Every skip is now tracked (no more silent failures)
- ✅ Diagnostics shown automatically after runs
- ✅ Prod mode requires confirmation
- ✅ Training mode enables safe research on real markets

## 🧪 Testing

After installation:

```bash
# Run all tests
pytest tests/test_modes_and_diagnostics.py -v

# Expected output:
# test_mode_validation PASSED
# test_skip_reason_structure PASSED  
# test_training_executor_never_trades PASSED
# test_decide_returns_skip_for_empty_orderbook PASSED
# test_decide_returns_skip_for_wide_spread PASSED
```

## 📊 Example Workflows

### Research on Real Markets (Safe)
```bash
export KALSHI_ENV=prod
export CASTLE_MODE=training
export ALLOW_TAKER_IN_PAPER=true

castle run --minutes 30
castle eval <run_id>
cat runs/<run_id>/diagnostics.json
```

### Strategy Development (Paper)
```bash
export CASTLE_MODE=paper
castle run --minutes 10
```

### Demo Environment Testing
```bash
export KALSHI_ENV=demo
export CASTLE_MODE=demo
castle run --minutes 5
```

## ⚠️ Important Notes

1. **Training mode is safe by design** - The executor has no order submission code
2. **Prod mode requires explicit confirmation** - You'll be prompted before placing real orders
3. **All existing functionality preserved** - Default behavior unchanged
4. **Backups created automatically** - The install script backs up existing files

## 🆘 Troubleshooting

### Issue: "No module named 'castle.execution.training'"
**Solution:** Make sure training.py is in `src/castle/execution/training.py`

### Issue: pytest collects from proposals/
**Solution:** Copy the updated `pytest.ini` file

### Issue: Still getting 0 decisions
**Solution:** Check `diagnostics.json` to see skip reasons, then adjust:
- `spread_too_wide` → Increase `MAX_SPREAD_CENTS`
- `insufficient_depth` → Decrease `MIN_DEPTH_CONTRACTS`
- `edge_too_small` → Decrease `MIN_EDGE_PROB`

### Issue: Training mode shows 0 trades
**Solution:** This is expected! Training mode logs "would trade" but doesn't execute. Check `trades.csv` for entries with `mode="training"` and `external_order_id="TRAINING_WOULD_PLACE"`

## 🤝 Support

1. Read **DEPLOYMENT_GUIDE.md** for detailed installation steps
2. Check **BEFORE_AFTER.md** for examples
3. See **IMPLEMENTATION_SUMMARY.md** for technical details
4. Review test cases in `tests/test_modes_and_diagnostics.py`

## 📝 Version Info

- Package version: 1.0.0
- Compatible with: Castle Bot v0.1.0+
- Python requirement: 3.10+
- Dependencies: No new dependencies added

## ✨ What's Next

After installation, you can:
1. Run training mode on real markets for 30+ minutes
2. Analyze the diagnostics to understand market filtering
3. Adjust strategy parameters based on skip reasons
4. Use `castle improve propose` with better context
5. Iterate on strategy safely with training mode

---

**Ready to install?** Start with `./install.sh /path/to/castle-bot` or see DEPLOYMENT_GUIDE.md!
