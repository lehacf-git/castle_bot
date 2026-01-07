"""Tests for diagnostics tracking and mode validation."""

import pytest
from castle.diagnostics import RunDiagnostics
from castle.config import Settings, get_settings
from pathlib import Path


def test_diagnostics_initialization():
    """Test that diagnostics starts with zero counters."""
    d = RunDiagnostics()
    assert d.markets_fetched == 0
    assert d.decisions_generated == 0
    assert d.trades_filled_paper == 0
    assert len(d.skip_reasons) == 0


def test_diagnostics_log_skip():
    """Test skip reason tracking."""
    d = RunDiagnostics()
    d.log_skip("TICKER1", "spread_too_wide")
    d.log_skip("TICKER2", "insufficient_depth")
    
    assert len(d.skip_reasons) == 2
    assert d.skip_reasons["TICKER1"] == "spread_too_wide"
    assert d.skip_reasons["TICKER2"] == "insufficient_depth"


def test_diagnostics_to_dict():
    """Test diagnostics serialization."""
    d = RunDiagnostics()
    d.markets_fetched = 10
    d.decisions_generated = 5
    d.log_skip("TICKER1", "test_reason")
    
    result = d.to_dict()
    assert result["markets_fetched"] == 10
    assert result["decisions_generated"] == 5
    assert "skip_reasons_sample" in result


def test_diagnostics_summary():
    """Test human-readable summary."""
    d = RunDiagnostics()
    d.markets_fetched = 50
    d.markets_with_orderbooks = 30
    d.decisions_generated = 10
    d.markets_spread_too_wide = 15
    
    summary = d.summary()
    assert "Markets fetched: 50" in summary
    assert "Decisions generated: 10" in summary
    assert "Spread too wide: 15" in summary


def test_settings_validate_mode_valid():
    """Test that valid modes pass validation."""
    valid_modes = ["test", "paper", "training", "demo", "prod"]
    
    for mode in valid_modes:
        # This should not raise for basic mode validation
        # (some modes will fail on missing credentials, but that's expected)
        try:
            s = Settings(
                db_url="sqlite:///test.db",
                runs_dir=Path("./runs"),
                log_level="INFO",
                kalshi_env="demo" if mode in ["test", "paper"] else ("prod" if mode == "training" else "demo"),
                kalshi_key_id="test" if mode in ["demo", "prod"] else "",
                kalshi_private_key_path=Path("/tmp/test.pem") if mode in ["demo", "prod"] else None,
                kalshi_demo_root="https://demo-api.kalshi.co/trade-api/v2",
                kalshi_prod_root="https://api.elections.kalshi.com/trade-api/v2",
                mode=mode,
                bankroll_usd=500.0,
                max_risk_per_market_usd=20.0,
                max_total_exposure_usd=100.0,
                min_edge_prob=0.03,
                max_spread_cents=10,
                min_depth_contracts=50,
                maker_only=True,
                est_taker_fee_cents_per_contract=2,
                enable_taker_test=False,
                news_feeds=[],
                news_lookback_hours=24,
                news_api_key="",
                newsapi_query="",
                newsapi_language="en",
                newsapi_lookback_hours=24,
                gemini_api_key="",
                gemini_model="gemini-1.5-flash",
                codegen_provider="openai",
                openai_api_key="",
                openai_model="gpt-5.2",
                openai_base_url="https://api.openai.com/v1",
            )
            s.validate_mode()
        except ValueError as e:
            # Expected failures for missing credentials
            if mode in ["demo", "prod"] and "requires" in str(e):
                pass  # This is expected
            elif mode == "training" and "requires KALSHI_ENV=prod" in str(e):
                pass  # This is expected if env is not prod
            else:
                raise


def test_settings_validate_mode_invalid():
    """Test that invalid modes raise ValueError."""
    with pytest.raises(ValueError, match="Invalid mode"):
        s = Settings(
            db_url="sqlite:///test.db",
            runs_dir=Path("./runs"),
            log_level="INFO",
            kalshi_env="demo",
            kalshi_key_id="",
            kalshi_private_key_path=None,
            kalshi_demo_root="https://demo-api.kalshi.co/trade-api/v2",
            kalshi_prod_root="https://api.elections.kalshi.com/trade-api/v2",
            mode="invalid_mode",
            bankroll_usd=500.0,
            max_risk_per_market_usd=20.0,
            max_total_exposure_usd=100.0,
            min_edge_prob=0.03,
            max_spread_cents=10,
            min_depth_contracts=50,
            maker_only=True,
            est_taker_fee_cents_per_contract=2,
            enable_taker_test=False,
            news_feeds=[],
            news_lookback_hours=24,
            news_api_key="",
            newsapi_query="",
            newsapi_language="en",
            newsapi_lookback_hours=24,
            gemini_api_key="",
            gemini_model="gemini-1.5-flash",
            codegen_provider="openai",
            openai_api_key="",
            openai_model="gpt-5.2",
            openai_base_url="https://api.openai.com/v1",
        )
        s.validate_mode()


def test_settings_should_execute_trades():
    """Test that only demo/prod modes execute trades."""
    for mode in ["test", "paper", "training"]:
        s = Settings(
            db_url="sqlite:///test.db",
            runs_dir=Path("./runs"),
            log_level="INFO",
            kalshi_env="demo" if mode != "training" else "prod",
            kalshi_key_id="",
            kalshi_private_key_path=None,
            kalshi_demo_root="https://demo-api.kalshi.co/trade-api/v2",
            kalshi_prod_root="https://api.elections.kalshi.com/trade-api/v2",
            mode=mode,
            bankroll_usd=500.0,
            max_risk_per_market_usd=20.0,
            max_total_exposure_usd=100.0,
            min_edge_prob=0.03,
            max_spread_cents=10,
            min_depth_contracts=50,
            maker_only=True,
            est_taker_fee_cents_per_contract=2,
            enable_taker_test=False,
            news_feeds=[],
            news_lookback_hours=24,
            news_api_key="",
            newsapi_query="",
            newsapi_language="en",
            newsapi_lookback_hours=24,
            gemini_api_key="",
            gemini_model="gemini-1.5-flash",
            codegen_provider="openai",
            openai_api_key="",
            openai_model="gpt-5.2",
            openai_base_url="https://api.openai.com/v1",
        )
        assert s.should_execute_trades() == False


def test_settings_get_kalshi_root():
    """Test that correct Kalshi root is returned based on env."""
    s = Settings(
        db_url="sqlite:///test.db",
        runs_dir=Path("./runs"),
        log_level="INFO",
        kalshi_env="demo",
        kalshi_key_id="",
        kalshi_private_key_path=None,
        kalshi_demo_root="https://demo-api.kalshi.co/trade-api/v2",
        kalshi_prod_root="https://api.elections.kalshi.com/trade-api/v2",
        mode="paper",
        bankroll_usd=500.0,
        max_risk_per_market_usd=20.0,
        max_total_exposure_usd=100.0,
        min_edge_prob=0.03,
        max_spread_cents=10,
        min_depth_contracts=50,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=False,
        news_feeds=[],
        news_lookback_hours=24,
        news_api_key="",
        newsapi_query="",
        newsapi_language="en",
        newsapi_lookback_hours=24,
        gemini_api_key="",
        gemini_model="gemini-1.5-flash",
        codegen_provider="openai",
        openai_api_key="",
        openai_model="gpt-5.2",
        openai_base_url="https://api.openai.com/v1",
    )
    
    assert "demo-api.kalshi.co" in s.get_kalshi_root()
    
    # Test prod
    s_prod = Settings(
        db_url="sqlite:///test.db",
        runs_dir=Path("./runs"),
        log_level="INFO",
        kalshi_env="prod",
        kalshi_key_id="test",
        kalshi_private_key_path=Path("/tmp/test.pem"),
        kalshi_demo_root="https://demo-api.kalshi.co/trade-api/v2",
        kalshi_prod_root="https://api.elections.kalshi.com/trade-api/v2",
        mode="training",
        bankroll_usd=500.0,
        max_risk_per_market_usd=20.0,
        max_total_exposure_usd=100.0,
        min_edge_prob=0.03,
        max_spread_cents=10,
        min_depth_contracts=50,
        maker_only=True,
        est_taker_fee_cents_per_contract=2,
        enable_taker_test=False,
        news_feeds=[],
        news_lookback_hours=24,
        news_api_key="",
        newsapi_query="",
        newsapi_language="en",
        newsapi_lookback_hours=24,
        gemini_api_key="",
        gemini_model="gemini-1.5-flash",
        codegen_provider="openai",
        openai_api_key="",
        openai_model="gpt-5.2",
        openai_base_url="https://api.openai.com/v1",
    )
    
    assert "api.elections.kalshi.com" in s_prod.get_kalshi_root()
