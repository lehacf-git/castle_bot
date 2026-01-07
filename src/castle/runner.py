# PATCH for src/castle/runner.py
# Adds diagnostics, training mode, and skip reason logging

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .config import Settings
from .kalshi.client import KalshiClient
from .models import Market, OrderbookSnapshot, NewsItem, Decision, Trade, Position
from .news.rss import parse_rss
from .news.newsapi import fetch_newsapi_everything
from .strategy.edge_strategy import decide, SkipReason
from .execution.paper import PaperExecutor
from .execution.kalshi_exec import KalshiExecutor
from .execution.training import TrainingExecutor
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


def ingest_markets_and_orderbooks(session: Session, kc: KalshiClient, now: dt.datetime, limit_markets: int = 50) -> list[tuple[str, str, list, list]]:
    # Grab open markets
    resp = kc.list_markets(status="open", limit=limit_markets)
    markets = resp.get("markets") or []
    out = []
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
    start = now - dt.timedelta(hours=lookback_hours)
    rows = session.execute(select(NewsItem.ts, NewsItem.title).where(NewsItem.ts >= start)).all()
    return [(r[0], r[1]) for r in rows]

def load_positions(session: Session) -> dict[tuple[str, str], PositionState]:
    pos: dict[tuple[str, str], PositionState] = {}
    rows = session.execute(select(Position)).scalars().all()
    for r in rows:
        pos[(r.ticker, r.side)] = PositionState(qty=int(r.qty), avg_price_cents=float(r.avg_price_cents))
    return pos

def save_positions(session: Session, pos: dict[tuple[str, str], PositionState], now: dt.datetime) -> None:
    # Simple full refresh
    session.execute(delete(Position))
    for (ticker, side), p in pos.items():
        session.add(Position(ticker=ticker, side=side, qty=p.qty, avg_price_cents=p.avg_price_cents, updated_at=now))
    session.commit()

def exposure_usd(pos: dict[tuple[str, str], PositionState]) -> float:
    # conservative: cost basis
    cents = 0.0
    for _, p in pos.items():
        cents += p.qty * p.avg_price_cents
    return cents / 100.0

def run_loop(*, engine, settings: Settings, minutes: int, mode: str, limit_markets: int = 40) -> Path:
    # Validate mode
    valid_modes = {"test", "paper", "training", "demo", "prod"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of: {', '.join(valid_modes)}")
    
    # Safety check: training mode requires prod env
    if mode == "training" and settings.kalshi_env != "prod":
        log.warning("Training mode works best with KALSHI_ENV=prod. Currently: %s", settings.kalshi_env)
    
    # Safety check: prod mode requires explicit prod env
    if mode == "prod" and settings.kalshi_env != "prod":
        raise ValueError("PROD trading mode requires KALSHI_ENV=prod")
    
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging to file
    import os as _os
    setup_logging(_os.getenv('CASTLE_LOG_LEVEL', 'INFO'), run_dir / 'logs.txt')
    import logging as _logging
    _logging.getLogger(__name__).info('Logging to %s', run_dir / 'logs.txt')
    log_file = run_dir / "logs.txt"

    # Configure file logging
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(fh)

    log.info("=== Starting run %s ===", run_id)
    log.info("Mode: %s | Env: %s | Minutes: %d", mode, settings.kalshi_env, minutes)

    cfg_dump = {k: str(v) for k, v in asdict(settings).items()}
    write_json(run_dir / "config.redacted.json", redact_config(cfg_dump))

    # Create Kalshi client pointing to the right environment
    kc = KalshiClient(
        root=settings.get_kalshi_root(),
        key_id=settings.kalshi_key_id or None,
        private_key_path=str(settings.kalshi_private_key_path) if settings.kalshi_private_key_path else None,
    )

    # Initialize executors
    paper = PaperExecutor()
    training = TrainingExecutor()
    live = KalshiExecutor(kc) if mode in {"demo", "prod"} else None

    # Diagnostics counters
    diagnostics = {
        "markets_seen": 0,
        "markets_with_orderbooks": 0,
        "decisions_generated": 0,
        "orders_attempted": 0,
        "trades_filled": 0,
        "skip_reasons": Counter(),
    }

    trades_rows = []
    equity_rows = []
    decisions_rows = []
    skips_rows = []  # Track skip reasons for analysis

    start = _utcnow()
    end = start + dt.timedelta(minutes=minutes)

    with Session(engine) as session:
        pos = load_positions(session)
        cash_usd = float(settings.bankroll_usd)

        while _utcnow() < end:
            now = _utcnow()
            ingest_news(session, settings, now)
            news = load_recent_news(session, now, settings.news_lookback_hours)

            md = ingest_markets_and_orderbooks(session, kc, now, limit_markets=limit_markets)
            diagnostics["markets_seen"] += len(md)
            diagnostics["markets_with_orderbooks"] += sum(1 for _, _, yes, no in md if yes or no)
            
            log.info("Cycle: %d markets fetched, %d with non-empty orderbooks", 
                    len(md), diagnostics["markets_with_orderbooks"])

            mids_yes = {}
            from .strategy.orderbook_math import best_prices, mid_prob
            for ticker, title, yes, no in md:
                bp = best_prices(yes, no)
                pm = mid_prob(bp.best_yes_bid, bp.best_yes_ask)
                if pm is not None:
                    mids_yes[ticker] = pm

            total_expo = exposure_usd(pos)

            # Determine effective maker_only based on mode and config
            effective_maker_only = settings.maker_only
            if mode in {"paper", "training"} and settings.allow_taker_in_paper:
                effective_maker_only = False
                log.debug("Taker mode enabled for %s testing", mode)

            for ticker, title, yes, no in md:
                decision, skip = decide(
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
                    maker_only=effective_maker_only,
                    est_taker_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                )
                
                if skip:
                    diagnostics["skip_reasons"][skip.reason] += 1
                    skips_rows.append({
                        "ts": now.isoformat(),
                        "ticker": skip.ticker,
                        "reason": skip.reason,
                        "detail": skip.detail,
                    })
                    continue
                
                if not decision:
                    continue

                diagnostics["decisions_generated"] += 1
                log.info("Decision: %s %s %s @ %d x%d (edge=%.3f)", 
                        decision.ticker, decision.side, decision.action,
                        decision.price_cents, decision.count, decision.edge)

                # Store decision
                session.add(Decision(
                    run_id=run_id,
                    ts=now,
                    ticker=decision.ticker,
                    side=decision.side,
                    action=decision.action,
                    price_cents=decision.price_cents,
                    count=decision.count,
                    p_market=decision.p_market,
                    p_model=decision.p_model,
                    edge=decision.edge,
                    reason=decision.reason,
                ))
                session.commit()
                decisions_rows.append({
                    "ts": now.isoformat(),
                    **decision.__dict__,
                })

                # Execute based on mode
                filled = None
                diagnostics["orders_attempted"] += 1
                
                if mode == "paper":
                    filled = paper.try_fill(
                        now=now,
                        ticker=decision.ticker,
                        side=decision.side,
                        action=decision.action,
                        price_cents=decision.price_cents,
                        count=decision.count,
                        yes_bids=yes,
                        no_bids=no,
                        maker_only=effective_maker_only,
                        est_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                    )
                    if filled:
                        diagnostics["trades_filled"] += 1
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
                        })
                        key = (filled.ticker, filled.side)
                        pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), filled.price_cents, filled.count)
                        cash_usd -= (filled.price_cents / 100.0) * filled.count
                        cash_usd -= (filled.fee_cents / 100.0)
                        total_expo = exposure_usd(pos)
                
                elif mode == "training":
                    # Training mode: log "would place" but don't actually trade
                    result = training.would_place_order(
                        now=now,
                        ticker=decision.ticker,
                        side=decision.side,
                        action=decision.action,
                        price_cents=decision.price_cents,
                        count=decision.count,
                        est_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                    )
                    diagnostics["trades_filled"] += 1  # "would have" filled
                    log.info("TRAINING: Would place order %s %s @ %d x%d",
                            result.ticker, result.side, result.price_cents, result.count)
                    
                    session.add(Trade(
                        run_id=run_id, ts=result.ts, ticker=result.ticker, side=result.side,
                        action=result.action, price_cents=result.price_cents, count=result.count,
                        fee_cents=result.fee_cents, mode="training", 
                        external_order_id=result.external_order_id
                    ))
                    session.commit()
                    trades_rows.append({
                        "ts": result.ts.isoformat(),
                        "ticker": result.ticker,
                        "side": result.side,
                        "action": result.action,
                        "price_cents": result.price_cents,
                        "count": result.count,
                        "fee_cents": result.fee_cents,
                        "mode": "training",
                        "external_order_id": result.external_order_id,
                    })
                    # For training, simulate position tracking
                    key = (result.ticker, result.side)
                    pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), result.price_cents, result.count)
                    cash_usd -= (result.price_cents / 100.0) * result.count
                    cash_usd -= (result.fee_cents / 100.0)
                    total_expo = exposure_usd(pos)

                elif mode in {"demo", "prod", "test"}:
                    # Live trading or test mode
                    assert live is not None
                    result = live.submit_limit_buy(
                        now=now, 
                        ticker=decision.ticker, 
                        side=decision.side, 
                        count=decision.count, 
                        price_cents=decision.price_cents
                    )
                    diagnostics["trades_filled"] += 1
                    session.add(Trade(
                        run_id=run_id, ts=result.ts, ticker=result.ticker, side=result.side,
                        action=result.action, price_cents=result.price_cents, count=result.count,
                        fee_cents=result.fee_cents, mode=mode, external_order_id=result.external_order_id
                    ))
                    session.commit()
                    trades_rows.append({
                        "ts": result.ts.isoformat(),
                        "ticker": result.ticker,
                        "side": result.side,
                        "action": result.action,
                        "price_cents": result.price_cents,
                        "count": result.count,
                        "fee_cents": result.fee_cents,
                        "mode": mode,
                        "external_order_id": result.external_order_id,
                    })
                    key = (result.ticker, result.side)
                    pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), result.price_cents, result.count)
                    total_expo = exposure_usd(pos)

            # equity snapshot
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

    # Write artifacts
    write_csv(run_dir / "trades.csv", trades_rows)
    write_csv(run_dir / "equity.csv", equity_rows)
    write_csv(run_dir / "decisions.csv", decisions_rows)
    write_csv(run_dir / "skips.csv", skips_rows)

    # Write diagnostics
    diag_json = {
        "markets_seen": diagnostics["markets_seen"],
        "markets_with_orderbooks": diagnostics["markets_with_orderbooks"],
        "decisions_generated": diagnostics["decisions_generated"],
        "orders_attempted": diagnostics["orders_attempted"],
        "trades_filled": diagnostics["trades_filled"],
        "skip_reasons": dict(diagnostics["skip_reasons"]),
    }
    write_json(run_dir / "diagnostics.json", diag_json)
    
    log.info("=== Run diagnostics ===")
    log.info("Markets seen: %d", diagnostics["markets_seen"])
    log.info("Markets with orderbooks: %d", diagnostics["markets_with_orderbooks"])
    log.info("Decisions generated: %d", diagnostics["decisions_generated"])
    log.info("Orders attempted: %d", diagnostics["orders_attempted"])
    log.info("Trades filled: %d", diagnostics["trades_filled"])
    log.info("Skip reasons: %s", dict(diagnostics["skip_reasons"].most_common(5)))

    # Prices at end of run
    try:
        prices_end = {
            "ts": _utcnow().isoformat(),
            "yes_mid_cents": {t: int(round(p * 100)) for t, p in mids_yes.items() if p is not None},
        }
        write_json(run_dir / "prices_end.json", prices_end)
    except Exception as e:
        log.warning("Failed to write prices_end.json: %s", e)

    # Summary
    summary = {
        "run_id": run_id,
        "mode": mode,
        "kalshi_env": settings.kalshi_env,
        "started_at": start.isoformat(),
        "ended_at": _utcnow().isoformat(),
        "minutes": minutes,
        "trades": len(trades_rows),
        "decisions": len(decisions_rows),
        "diagnostics": diag_json,
    }
    write_json(run_dir / "summary.json", summary)
    log.info("Run summary: %s", summary)

    # Extra per-run summary
    try:
        write_run_summary(run_dir)
    except Exception as e:
        log.warning("Failed to write run_summary: %s", e)

    return run_dir
