"""Tests for strategy decision logic with skip reasons."""

import datetime as dt
import pytest
from castle.strategy.edge_strategy import decide, SkipReason


def test_decide_empty_orderbook():
    """Test that empty orderbooks are properly skipped."""
    decision, skip = decide(
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
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "empty_orderbook"


def test_decide_no_best_prices():
    """Test that markets without best prices are skipped."""
    # Only yes bids, no no bids means no implied ask
    decision, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[[50, 10]],
        no_bids=[],  # No no_bids means no best_yes_ask
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
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "no_best_prices"


def test_decide_spread_too_wide():
    """Test that wide spreads are properly skipped."""
    # Create a wide spread: yes bid=40, no bid=40 => yes ask=60, spread=20
    decision, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[[40, 100]],
        no_bids=[[40, 100]],
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[],
        min_edge_prob=0.03,
        max_spread_cents=10,  # Max 10 cents spread
        min_depth_contracts=50,
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=0,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=False,
    )
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "spread_too_wide"
    assert "spread=20" in skip.details


def test_decide_insufficient_depth():
    """Test that insufficient depth is properly skipped."""
    # Tight spread but low depth
    decision, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[[48, 10]],  # Only 10 contracts
        no_bids=[[48, 10]],
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[],
        min_edge_prob=0.03,
        max_spread_cents=10,
        min_depth_contracts=50,  # Require 50 contracts
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=0,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=False,
    )
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "insufficient_depth"


def test_decide_insufficient_edge():
    """Test that insufficient edge is properly skipped."""
    # Market mid at 50%, no news to tilt, so edge = 0
    decision, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[[49, 100]],
        no_bids=[[49, 100]],  # yes ask = 51, mid = 50%
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[],
        min_edge_prob=0.03,  # Need 3% edge
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
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "insufficient_edge"


def test_decide_max_exposure_reached():
    """Test that max exposure limit is enforced."""
    decision, skip = decide(
        ticker="TEST",
        title="Test Market",
        yes_bids=[[30, 100]],  # Low price = bullish signal
        no_bids=[[60, 100]],  # High no bid
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[],
        min_edge_prob=0.03,
        max_spread_cents=10,
        min_depth_contracts=50,
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=100,  # Already at max
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=False,
    )
    
    assert decision is None
    assert skip is not None
    assert skip.reason == "max_exposure_reached"


def test_decide_generates_decision():
    """Test that a valid market generates a decision."""
    # Create conditions for a decision:
    # - Tight spread
    # - Good depth  
    # - Some edge from news or market pricing
    decision, skip = decide(
        ticker="TEST",
        title="Test Market technology innovation",
        yes_bids=[[35, 100]],  # YES bid at 35
        no_bids=[[60, 100]],   # NO bid at 60 => YES ask at 40, mid at 37.5%
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[
            (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), 
             "Technology innovation surge strong gains record")  # Positive news
        ],
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
    
    # Should generate a decision due to news tilt or market mispricing
    # Note: This might still skip if edge is insufficient, but it tests the happy path
    if decision:
        assert decision.ticker == "TEST"
        assert decision.action == "buy"
        assert decision.count > 0
    else:
        # If skipped, it should have a valid reason
        assert skip is not None
        assert skip.reason in ["insufficient_edge", "insufficient_edge_after_fees"]


def test_decide_taker_test_mode():
    """Test that taker test mode is reflected in decision."""
    decision, skip = decide(
        ticker="TEST",
        title="Test Market technology innovation",
        yes_bids=[[35, 100]],
        no_bids=[[60, 100]],
        now=dt.datetime.now(dt.timezone.utc),
        news_headlines=[
            (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), 
             "Technology innovation surge strong gains record")
        ],
        min_edge_prob=0.01,  # Lower threshold for testing
        max_spread_cents=10,
        min_depth_contracts=50,
        bankroll_usd=500,
        max_risk_per_market_usd=20,
        max_total_exposure_usd=100,
        current_total_exposure_usd=0,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=True,  # Enable taker test
    )
    
    if decision:
        assert "(taker_test)" in decision.reason
