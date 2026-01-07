from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List
import os

from dotenv import load_dotenv

load_dotenv()

def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name, str(default)).strip().lower()
    return v in {"1", "true", "yes", "y", "on"}

def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)

def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default)

def _list_csv(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]

@dataclass(frozen=True)
class Settings:
    # General
    db_url: str
    runs_dir: Path
    log_level: str

    # Kalshi
    kalshi_env: str
    kalshi_key_id: str
    kalshi_private_key_path: Path | None
    kalshi_demo_root: str
    kalshi_prod_root: str

    # Mode
    mode: str

    # Strategy / Risk
    bankroll_usd: float
    max_risk_per_market_usd: float
    max_total_exposure_usd: float
    min_edge_prob: float
    max_spread_cents: int
    min_depth_contracts: int
    maker_only: bool
    est_taker_fee_cents_per_contract: int

    # Strategy enhancements
    decision_cooldown_seconds: int
    enable_taker_test: bool  # For paper/training: test taker logic even if maker_only=true

    # News (RSS)
    news_feeds: List[str]
    news_lookback_hours: int

    # News (NewsAPI.org)
    news_api_key: str
    newsapi_query: str
    newsapi_language: str
    newsapi_lookback_hours: int

    # LLM (Gemini)
    gemini_api_key: str
    gemini_model: str

    # Codegen / Analytics (OpenAI)
    codegen_provider: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str

def get_settings() -> Settings:
    # Kalshi env vars: accept both naming conventions.
    # Preferred:
    # - KALSHI_API_KEY_ID
    # - KALSHI_PRIVATE_KEY_PATH
    # Back-compat:
    # - KALSHI_KEY_ID
    key_id = _str("KALSHI_API_KEY_ID", "").strip() or _str("KALSHI_KEY_ID", "").strip()
    pk = _str("KALSHI_PRIVATE_KEY_PATH", "").strip()

    return Settings(
        db_url=_str("CASTLE_DB_URL", "sqlite:///castle.db"),
        runs_dir=Path(_str("CASTLE_RUNS_DIR", "./runs")).expanduser(),
        log_level=_str("CASTLE_LOG_LEVEL", "INFO"),

        kalshi_env=_str("KALSHI_ENV", "demo"),
        kalshi_key_id=key_id,
        kalshi_private_key_path=Path(pk).expanduser() if pk else None,
        kalshi_demo_root=_str("KALSHI_DEMO_ROOT", "https://demo-api.kalshi.co/trade-api/v2"),
        kalshi_prod_root=_str("KALSHI_PROD_ROOT", "https://api.elections.kalshi.com/trade-api/v2"),

        mode=_str("CASTLE_MODE", "paper"),

        bankroll_usd=_float("BANKROLL_USD", 500),
        max_risk_per_market_usd=_float("MAX_RISK_PER_MARKET_USD", 20),
        max_total_exposure_usd=_float("MAX_TOTAL_EXPOSURE_USD", 100),
        min_edge_prob=_float("MIN_EDGE_PROB", 0.03),
        max_spread_cents=_int("MAX_SPREAD_CENTS", 10),
        min_depth_contracts=_int("MIN_DEPTH_CONTRACTS", 50),
        maker_only=_bool("MAKER_ONLY", True),
        est_taker_fee_cents_per_contract=_int("EST_TAKER_FEE_CENTS_PER_CONTRACT", 2),

        decision_cooldown_seconds=_int("DECISION_COOLDOWN_SECONDS", 60),
        enable_taker_test=_bool("ENABLE_TAKER_TEST", False),

        news_feeds=_list_csv("NEWS_FEEDS"),
        news_lookback_hours=_int("NEWS_LOOKBACK_HOURS", 24),

        news_api_key=_str("NEWS_API_KEY", "").strip(),
        newsapi_query=_str("NEWSAPI_QUERY", "").strip(),
        newsapi_language=_str("NEWSAPI_LANGUAGE", "en").strip(),
        newsapi_lookback_hours=_int("NEWSAPI_LOOKBACK_HOURS", 24),

        gemini_api_key=_str("GEMINI_API_KEY", "").strip(),
        gemini_model=_str("GEMINI_MODEL", "gemini-1.5-flash").strip(),

        codegen_provider=_str("CODEGEN_PROVIDER", "openai").strip().lower(),
        openai_api_key=_str("OPENAI_API_KEY", "").strip(),
        openai_model=_str("OPENAI_MODEL", "gpt-5.2").strip(),
        openai_base_url=_str("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
    )
