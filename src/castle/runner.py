"""
Castle Bot Runner - Main trading loop

Supports 4 modes:
- paper: Simulated fills, no real trading
- training: Real market data, logs "would_trade", no execution
- demo: Real trades on Kalshi demo environment  
- prod: Real trades on Kalshi production (REAL MONEY!)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .config import Settings
from .kalshi.client import KalshiClient
from .models import Market, OrderbookSnapshot, NewsItem, Decision, Trade, Position
from .news.rss import parse_rss
from .news.newsapi import fetch_newsapi_everything
from .strategy.edge_strategy import decide
from .execution.paper import PaperExecutor
from .execution.training import TrainingExecutor
from .execution.kalshi_exec import KalshiExecutor
from .portfolio import PositionState, apply_buy, mark_to_market_usd
from .logging import setup_logging
from .reporting import write_csv, write_json, redact_config
from .run_summary import write_run_summary

log = logging.getLogger(__name__)


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def init_db(engine) -> None:
    from .db import Base
    Base.metadata.create_all(bind=engine)


def ingest_news(session: Session, settings: Settings, now: dt.datetime) -> int:
    """Ingest news from RSS feeds and NewsAPI."""
    inserted = 0

    # RSS feeds
    if settings.news_feeds:
        for url in settings.news_feeds:
            try:
                items = parse_rss(url)
            except Exception as e:
                log.warning("RSS parse failed: %s %s", url, e)
                continue
            for it in items:
                exists = session.execute(select(NewsItem).where(NewsItem.url == it["url"])).scalar_one_or_none()
                if exists:
                    continue
                session.add(NewsItem(
                    ts=it["ts"],
                    source=url,
                    title=it["title"][:500],
                    url=it["url"][:1000],
                    summary=it["summary"][:5000],
                ))
                inserted += 1

    # NewsAPI.org (optional)
    if settings.news_api_key and settings.newsapi_query:
        try:
            items = fetch_newsapi_everything(
                api_key=settings.news_api_key,
                query=settings.newsapi_query,
                language=settings.newsapi_language,
                lookback_hours=settings.newsapi_lookback_hours,
                page_size=50,
            )
            for it in items:
                exists = session.execute(select(NewsItem).where(NewsItem.url == it["url"])).scalar_one_or_none()
                if exists:
                    continue
                session.add(NewsItem(
                    ts=it["ts"],
                    source="newsapi",
                    title=it["title"][:500],
                    url=it["url"][:1000],
                    summary=it["summary"][:5000],
                ))
                inserted += 1
        except Exception as e:
            log.warning("NewsAPI fetch failed: %s", e)

    session.commit()
    return inserted


def ingest_markets_and_orderbooks(
    session: Session, 
    kc: KalshiClient, 
    now: dt.datetime, 
    limit_markets: int = 50
) -> list[tuple[str, str, list, list]]:
    """Fetch markets and orderbooks from Kalshi."""
    resp = kc.list_markets(status="open", limit=limit_markets)
    markets = resp.get("markets") or []
    out = []
    
    log.info(f"Fetched {len(markets)} open markets")
    
    for m in markets:
        ticker = m.get("ticker")
        title = m.get("title") or ""
        status = m.get("status") or ""
        close_time = m.get("close_time")
        close_dt = None
        if close_time:
            try:
                close_dt = dt.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            except Exception:
                close_dt = None
        
        session.merge(Market(
            ticker=ticker,
            title=title[:500],
            status=status,
            close_time=close_dt,
            raw_json=json.dumps(m),
            updated_at=now,
        ))
        
        try:
            ob = kc.get_orderbook(ticker)
            obk = ob.get("orderbook") or {}
            yes = obk.get("yes") or []
            no = obk.get("no") or []
        except Exception as e:
            log.warning("Orderbook failed %s: %s", ticker, e)
            continue
        
        session.add(OrderbookSnapshot(
            ticker=ticker,
            ts=now,
            yes_bids_json=json.dumps(yes),
            no_bids_json=json.dumps(no),
        ))
        out.append((ticker, title, yes, no))
    
    session.commit()
    return out


def load_recent_news(session: Session, now: dt.datetime, lookback_hours: int) -> list[tuple[dt.datetime, str]]:
    """Load recent news headlines from database."""
    start = now - dt.timedelta(hours=lookback_hours)
    rows = session.execute(select(NewsItem.ts, NewsItem.title).where(NewsItem.ts >= start)).all()
    return [(r[0], r[1]) for r in rows]


def load_positions(session: Session) -> dict[tuple[str, str], PositionState]:
    """Load current positions from database."""
    pos: dict[tuple[str, str], PositionState] = {}
    rows = session.execute(select(Position)).scalars().all()
    for r in rows:
        pos[(r.ticker, r.side)] = PositionState(qty=int(r.qty), avg_price_cents=float(r.avg_price_cents))
    return pos


def save_positions(session: Session, pos: dict[tuple[str, str], PositionState], now: dt.datetime) -> None:
    """Save positions to database."""
    session.execute(delete(Position))
    for (ticker, side), p in pos.items():
        session.add(Position(ticker=ticker, side=side, qty=p.qty, avg_price_cents=p.avg_price_cents, updated_at=now))
    session.commit()


def exposure_usd(pos: dict[tuple[str, str], PositionState]) -> float:
    """Calculate total exposure in USD (cost basis)."""
    cents = 0.0
    for _, p in pos.items():
        cents += p.qty * p.avg_price_cents
    return cents / 100.0


def run_loop(*, engine, settings: Settings, minutes: int, mode: str, limit_markets: int = 40) -> Path:
    """
    Main trading loop.
    
    Args:
        engine: SQLAlchemy engine
        settings: Configuration settings
        minutes: How long to run
        mode: One of 'paper', 'training', 'demo', 'prod'
        limit_markets: Max markets to scan per cycle
    
    Returns:
        Path to run directory
    """
    # Validate mode
    mode = mode.lower().strip()
    if mode not in {"paper", "training", "demo", "prod"}:
        raise ValueError(f"Invalid mode: {mode}. Must be paper|training|demo|prod")
    
    # Setup run directory
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    import os as _os
    setup_logging(_os.getenv('CASTLE_LOG_LEVEL', 'INFO'), run_dir / 'logs.txt')
    log.info(f"Starting run {run_id} in {mode.upper()} mode")
    log.info(f"Run directory: {run_dir}")
    
    # Log mode-specific info
    if mode == "training":
        log.info("=" * 60)
        log.info("TRAINING MODE ACTIVE")
        log.info("Using PRODUCTION market data")
        log.info("NO ORDERS WILL BE PLACED")
        log.info("All decisions logged as 'would_trade'")
        log.info("=" * 60)
    elif mode == "prod":
        log.warning("=" * 60)
        log.warning("PRODUCTION MODE - REAL MONEY TRADING")
        log.warning("=" * 60)
    
    # Save redacted config
    cfg_dump = {k: str(v) for k, v in asdict(settings).items()}
    write_json(run_dir / "config.redacted.json", redact_config(cfg_dump))
    
    # Initialize Kalshi client
    # Training mode uses PROD API for data but never trades
    if mode == "training":
        api_root = settings.kalshi_prod_root
        log.info(f"Training mode: Using production API for data: {api_root}")
    elif settings.kalshi_env == "demo":
        api_root = settings.kalshi_demo_root
    else:
        api_root = settings.kalshi_prod_root
    
    kc = KalshiClient(
        root=api_root,
        key_id=settings.kalshi_key_id or None,
        private_key_path=str(settings.kalshi_private_key_path) if settings.kalshi_private_key_path else None,
    )
    
    # Initialize executors based on mode
    paper = PaperExecutor()
    training = TrainingExecutor() if mode == "training" else None
    live = KalshiExecutor(kc) if mode in {"demo", "prod"} else None
    
    # Safety check: training mode must NEVER have live executor
    if mode == "training":
        live = None
        log.info("Safety check: live executor disabled for training mode")
    
    # Initialize tracking
    trades_rows = []
    equity_rows = []
    decisions_rows = []
    skip_reasons_count: Dict[str, int] = {}  # Track why markets were skipped
    
    start = _utcnow()
    end = start + dt.timedelta(minutes=minutes)
    
    with Session(engine) as session:
        pos = load_positions(session) if mode != "training" else {}
        cash_usd = float(settings.bankroll_usd)
        
        cycle = 0
        while _utcnow() < end:
            cycle += 1
            now = _utcnow()
            log.info(f"Cycle {cycle} at {now.isoformat()}")
            
            # Ingest news
            news_count = ingest_news(session, settings, now)
            if news_count > 0:
                log.info(f"Ingested {news_count} new news items")
            
            news = load_recent_news(session, now, settings.news_lookback_hours)
            
            # Ingest markets and orderbooks
            md = ingest_markets_and_orderbooks(session, kc, now, limit_markets=limit_markets)
            log.info(f"Processing {len(md)} markets with orderbooks")
            
            # Calculate mid prices for MTM
            mids_yes = {}
            from .strategy.orderbook_math import best_prices, mid_prob
            for ticker, title, yes, no in md:
                bp = best_prices(yes, no)
                pm = mid_prob(bp.best_yes_bid, bp.best_yes_ask)
                if pm is not None:
                    mids_yes[ticker] = pm
            
            total_expo = exposure_usd(pos)
            decisions_this_cycle = 0
            
            for ticker, title, yes, no in md:
                # Call decide() and handle different return types
                result = decide(
                    ticker=ticker,
                    title=title,
                    yes_bids=yes,
                    no_bids=no,
                    now=now,
                    news_headlines=news,
                    min_edge_prob=settings.min_edge_prob,
                    max_spread_cents=settings.max_spread_cents,
                    min_depth_contracts=settings.min_depth_contracts,
                    bankroll_usd=settings.bankroll_usd,
                    max_risk_per_market_usd=settings.max_risk_per_market_usd,
                    max_total_exposure_usd=settings.max_total_exposure_usd,
                    current_total_exposure_usd=total_expo,
                    maker_only=settings.maker_only,
                    est_taker_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                )
                
                # Handle different return types from decide()
                # Could be: None, DecisionCandidate, or (DecisionCandidate, SkipReason) tuple
                cand = None
                skip_reason = None
                
                if result is None:
                    # No decision, no skip reason
                    continue
                elif isinstance(result, tuple):
                    # New format: (candidate, skip_reason)
                    cand, skip_reason = result
                    if skip_reason is not None:
                        reason_key = getattr(skip_reason, 'reason', 'unknown')
                        skip_reasons_count[reason_key] = skip_reasons_count.get(reason_key, 0) + 1
                        log.debug(f"Skipped {ticker}: {reason_key}")
                    if cand is None:
                        continue
                else:
                    # Old format: just the candidate
                    cand = result
                
                # At this point, cand should be a valid DecisionCandidate
                if cand is None:
                    continue
                
                # Verify cand has the expected attributes
                if not hasattr(cand, 'ticker'):
                    log.warning(f"Invalid candidate object: {type(cand)}")
                    continue
                
                decisions_this_cycle += 1
                
                # Store decision
                session.add(Decision(
                    run_id=run_id,
                    ts=now,
                    ticker=cand.ticker,
                    side=cand.side,
                    action=cand.action,
                    price_cents=cand.price_cents,
                    count=cand.count,
                    p_market=cand.p_market,
                    p_model=cand.p_model,
                    edge=cand.edge,
                    reason=cand.reason,
                ))
                session.commit()
                
                decisions_rows.append({
                    "ts": now.isoformat(),
                    "ticker": cand.ticker,
                    "side": cand.side,
                    "action": cand.action,
                    "price_cents": cand.price_cents,
                    "count": cand.count,
                    "p_market": cand.p_market,
                    "p_model": cand.p_model,
                    "edge": cand.edge,
                    "reason": cand.reason,
                })
                
                log.info(
                    f"Decision: {cand.action} {cand.count}x {cand.ticker} {cand.side} "
                    f"@ {cand.price_cents}¢ | edge={cand.edge:.3f}"
                )
                
                # Execute based on mode
                if mode == "paper":
                    filled = paper.try_fill(
                        now=now,
                        ticker=cand.ticker,
                        side=cand.side,
                        action=cand.action,
                        price_cents=cand.price_cents,
                        count=cand.count,
                        yes_bids=yes,
                        no_bids=no,
                        maker_only=settings.maker_only,
                        est_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                    )
                    if filled:
                        log.info(f"Paper fill: {filled.count}x {filled.ticker} @ {filled.price_cents}¢")
                        session.add(Trade(
                            run_id=run_id, ts=filled.ts, ticker=filled.ticker, side=filled.side,
                            action=filled.action, price_cents=filled.price_cents, count=filled.count,
                            fee_cents=filled.fee_cents, mode="paper", external_order_id=None
                        ))
                        session.commit()
                        trades_rows.append({
                            "ts": filled.ts.isoformat(),
                            "ticker": filled.ticker,
                            "side": filled.side,
                            "action": filled.action,
                            "price_cents": filled.price_cents,
                            "count": filled.count,
                            "fee_cents": filled.fee_cents,
                            "mode": "paper",
                            "external_order_id": "",
                            "executed": True,
                        })
                        key = (filled.ticker, filled.side)
                        pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), filled.price_cents, filled.count)
                        cash_usd -= (filled.price_cents / 100.0) * filled.count
                        cash_usd -= (filled.fee_cents / 100.0)
                        total_expo = exposure_usd(pos)
                
                elif mode == "training":
                    # Training mode: log what we WOULD trade, no execution
                    assert training is not None
                    would = training.record_would_trade(
                        now=now,
                        ticker=cand.ticker,
                        side=cand.side,
                        action=cand.action,
                        price_cents=cand.price_cents,
                        count=cand.count,
                        reason=cand.reason,
                        p_market=cand.p_market,
                        p_model=cand.p_model,
                        edge=cand.edge,
                    )
                    trades_rows.append({
                        "ts": would.ts.isoformat(),
                        "ticker": would.ticker,
                        "side": would.side,
                        "action": would.action,
                        "price_cents": would.price_cents,
                        "count": would.count,
                        "fee_cents": 0,
                        "mode": "training",
                        "external_order_id": "",
                        "executed": False,
                    })
                    # Don't update positions - training mode doesn't track portfolio
                
                else:
                    # Live mode (demo or prod)
                    assert live is not None
                    log.warning(f"Submitting LIVE order: {cand.action} {cand.count}x {cand.ticker}")
                    res = live.submit_limit_buy(
                        now=now,
                        ticker=cand.ticker,
                        side=cand.side,
                        count=cand.count,
                        price_cents=cand.price_cents
                    )
                    session.add(Trade(
                        run_id=run_id, ts=res.ts, ticker=res.ticker, side=res.side,
                        action=res.action, price_cents=res.price_cents, count=res.count,
                        fee_cents=res.fee_cents, mode=mode, external_order_id=res.external_order_id
                    ))
                    session.commit()
                    trades_rows.append({
                        "ts": res.ts.isoformat(),
                        "ticker": res.ticker,
                        "side": res.side,
                        "action": res.action,
                        "price_cents": res.price_cents,
                        "count": res.count,
                        "fee_cents": res.fee_cents,
                        "mode": mode,
                        "external_order_id": res.external_order_id,
                        "executed": True,
                    })
                    key = (res.ticker, res.side)
                    pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), res.price_cents, res.count)
                    total_expo = exposure_usd(pos)
            
            log.info(f"Cycle {cycle} complete: {decisions_this_cycle} decisions")
            
            # Equity snapshot (skip for training mode)
            if mode != "training":
                mtm = mark_to_market_usd(pos, mids_yes)
                equity_rows.append({
                    "ts": now.isoformat(),
                    "cash_usd": round(cash_usd, 4),
                    "exposure_usd": round(total_expo, 4),
                    "mtm_value_usd": round(mtm, 4),
                    "equity_usd": round(cash_usd + mtm, 4),
                    "positions": sum(p.qty for p in pos.values()),
                })
                save_positions(session, pos, now)
            
            time.sleep(5)
    
    # Log skip reasons summary
    if skip_reasons_count:
        log.info("Skip reasons summary:")
        for reason, count in sorted(skip_reasons_count.items(), key=lambda x: -x[1]):
            log.info(f"  {reason}: {count}")
    
    # Write artifacts
    write_csv(run_dir / "trades.csv", trades_rows)
    write_csv(run_dir / "equity.csv", equity_rows)
    write_csv(run_dir / "decisions.csv", decisions_rows)
    
    # Write skip reasons
    if skip_reasons_count:
        write_json(run_dir / "skip_reasons.json", skip_reasons_count)
    
    # Write end prices
    try:
        prices_end = {
            "ts": _utcnow().isoformat(),
            "yes_mid_cents": {t: int(round(p * 100)) for t, p in mids_yes.items() if p is not None},
        }
        write_json(run_dir / "prices_end.json", prices_end)
    except Exception as e:
        log.warning("Failed to write prices_end.json: %s", e)
    
    # Training mode summary
    if mode == "training" and training is not None:
        training_summary = training.get_summary()
        log.info(f"Training summary: {training_summary}")
        write_json(run_dir / "training_summary.json", training_summary)
    
    # Summary
    summary = {
        "run_id": run_id,
        "mode": mode,
        "started_at": start.isoformat(),
        "ended_at": _utcnow().isoformat(),
        "minutes": minutes,
        "trades": len(trades_rows),
        "decisions": len(decisions_rows),
        "markets_scanned": len(md) if 'md' in dir() else 0,
        "skip_reasons": skip_reasons_count,
    }
    write_json(run_dir / "summary.json", summary)
    log.info("Run summary: %s", summary)
    
    # Extra per-run summary
    try:
        write_run_summary(run_dir)
    except Exception as e:
        log.warning("Failed to write run_summary: %s", e)
    
    log.info(f"Run complete: {run_dir}")
    return run_dir
