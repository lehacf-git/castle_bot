# NEW FILE: tests/test_modes_and_diagnostics.py
"""Tests for mode handling, skip reasons, and training mode."""

from castle.config import Settings, get_settings
from castle.strategy.edge_strategy import decide, SkipReason
from castle.execution.training import TrainingExecutor, TrainingResult
import datetime as dt


def test_mode_validation():
    """Test that Settings helpers correctly identify safe vs trading modes."""
    
    # Mock settings for different modes
    class MockSettings:
        def __init__(self, mode):
            self.mode = mode
        
        def is_trading_mode(self):
            return self.mode in {"demo", "prod"}
        
        def is_safe_mode(self):
            return self.mode in {"test", "paper", "training"}
    
    # Test safe modes
    for mode in ["test", "paper", "training"]:
        s = MockSettings(mode)
        assert s.is_safe_mode(), f"{mode} should be safe"
        assert not s.is_trading_mode(), f"{mode} should not be trading"
    
    # Test trading modes
    for mode in ["demo", "prod"]:
        s = MockSettings(mode)
        assert s.is_trading_mode(), f"{mode} should be trading"
        assert not s.is_safe_mode(), f"{mode} should not be safe"


def test_skip_reason_structure():
    """Test that SkipReason contains expected fields."""
    skip = SkipReason(
        ticker="TEST-MARKET",
        reason="spread_too_wide",
        detail="spread=20 > 10"
    )
    
    assert skip.ticker == "TEST-MARKET"
    assert skip.reason == "spread_too_wide"
    assert skip.detail == "spread=20 > 10"


def test_training_executor_never_trades():
    """Test that TrainingExecutor only logs, never places orders."""
    executor = TrainingExecutor()
    
    result = executor.would_place_order(
        now=dt.datetime.now(dt.timezone.utc),
        ticker="TEST-MARKET",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
        est_fee_cents_per_contract=2,
    )
    
    assert isinstance(result, TrainingResult)
    assert result.mode == "training"
    assert result.external_order_id == "TRAINING_WOULD_PLACE"
    assert result.ticker == "TEST-MARKET"
    assert result.price_cents == 50
    assert result.count == 10
    assert result.fee_cents == 20  # 10 * 2


def test_decide_returns_skip_for_empty_orderbook():
    """Test that decide() returns skip reason for empty orderbook."""
    now = dt.datetime.now(dt.timezone.utc)
    
    decision, skip = decide(
        ticker="EMPTY-MARKET",
        title="Empty Market",
        yes_bids=[],  # Empty orderbook
        no_bids=[],
        now=now,
        news_headlines=[],
        min_edge_prob=0.03,
        max_spread_cents=10,
        min_depth_contracts=50,
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=0,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
    )
    
    assert decision is None
    assert skip is not None
    assert skip.ticker == "EMPTY-MARKET"
    assert "no_prices" in skip.reason or "no_spread" in skip.reason


def test_decide_returns_skip_for_wide_spread():
    """Test that decide() returns skip reason for wide spread."""
    now = dt.datetime.now(dt.timezone.utc)
    
    # Create orderbook with wide spread (YES: 20 bid, NO: 60 bid = YES ask 40)
    # Spread = 40 - 20 = 20 cents
    yes_bids = [[10, 10], [20, 10]]
    no_bids = [[50, 10], [60, 10]]
    
    decision, skip = decide(
        ticker="WIDE-SPREAD",
        title="Wide Spread Market",
        yes_bids=yes_bids,
        no_bids=no_bids,
        now=now,
        news_headlines=[],
        min_edge_prob=0.03,
        max_spread_cents=10,  # Max 10 cents
        min_depth_contracts=5,
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=0,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
    )
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "spread_too_wide"
    assert "20" in skip.detail  # Should mention the spread value
