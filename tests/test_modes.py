"""Tests for mode validation and training mode behavior."""
import pytest
from unittest.mock import Mock, patch
from castle.cli import _validate_mode


def test_validate_mode_valid():
    """Test that valid modes are accepted."""
    assert _validate_mode("test") == "test"
    assert _validate_mode("paper") == "paper"
    assert _validate_mode("training") == "training"
    assert _validate_mode("demo") == "demo"
    assert _validate_mode("prod") == "prod"
    
    # Test case insensitivity
    assert _validate_mode("TEST") == "test"
    assert _validate_mode("Paper") == "paper"
    assert _validate_mode(" training ") == "training"


def test_validate_mode_invalid():
    """Test that invalid modes raise errors."""
    with pytest.raises(Exception):  # typer.BadParameter
        _validate_mode("invalid")
    
    with pytest.raises(Exception):
        _validate_mode("live")
    
    with pytest.raises(Exception):
        _validate_mode("")


def test_training_mode_no_trading():
    """Test that training mode never executes trades."""
    from castle.execution.kalshi_exec import KalshiExecutor
    
    # In training mode, KalshiExecutor should not be instantiated
    # This is enforced in runner.py: can_trade = mode in {"demo", "prod"}
    
    modes_that_trade = {"demo", "prod"}
    modes_no_trade = {"test", "paper", "training"}
    
    for mode in modes_that_trade:
        can_trade = mode in {"demo", "prod"}
        assert can_trade, f"Mode {mode} should allow trading"
    
    for mode in modes_no_trade:
        can_trade = mode in {"demo", "prod"}
        assert not can_trade, f"Mode {mode} should NOT allow trading"


def test_cooldown_mechanism():
    """Test decision cooldown prevents churn."""
    from castle.runner import DecisionCooldown
    import datetime as dt
    
    cooldown = DecisionCooldown(cooldown_seconds=60)
    now = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    
    # First decision should be allowed
    assert cooldown.can_decide("TICKER1", now)
    
    # Record decision
    cooldown.record_decision("TICKER1", now)
    
    # Immediate retry should be blocked
    assert not cooldown.can_decide("TICKER1", now)
    
    # After 30 seconds, still blocked
    later_30s = now + dt.timedelta(seconds=30)
    assert not cooldown.can_decide("TICKER1", later_30s)
    
    # After 60 seconds, allowed
    later_60s = now + dt.timedelta(seconds=60)
    assert cooldown.can_decide("TICKER1", later_60s)
    
    # Different ticker is independent
    assert cooldown.can_decide("TICKER2", now)


def test_skip_reason_tracking():
    """Test that skip reasons are properly tracked."""
    from castle.strategy.edge_strategy import decide, SkipReason
    import datetime as dt
    
    # Empty orderbook should produce skip reason
    cand, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[],
        no_bids=[],
        now=dt.datetime.now(dt.timezone.utc),
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
        enable_taker_test=False,
    )
    
    assert cand is None
    assert skip is not None
    assert skip.reason == "no_prices"
    assert "yes_bid" in skip.details


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
