from __future__ import annotations

import datetime as dt
import json
import logging
import time
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
from .strategy.edge_strategy import decide
from .execution.paper import PaperExecutor
from .execution.kalshi_exec import KalshiExecutor
from .portfolio import PositionState, apply_buy, mark_to_market_usd
from .logging import setup_logging
from .reporting import write_csv, write_json, redact_config
from .run_summary import write_run_summary
from .diagnostics import RunDiagnostics

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


def ingest_markets_and_orderbooks(
    session: Session, 
    kc: KalshiClient, 
    now: dt.datetime, 
    limit_markets: int = 50,
    min_volume_24h: int = 100,
    min_open_interest: int = 50,
    diagnostics: RunDiagnostics | None = None
) -> list[tuple[str, str, list, list]]:
    """
    Ingest markets with pagination support, volume filtering, and improved diagnostics.
    
    Fetches markets, ranks by liquidity (volume + open interest), and selects top N.
    
    Args:
        session: Database session
        kc: Kalshi API client
        now: Current timestamp
        limit_markets: Number of markets to select (after filtering)
        min_volume_24h: Minimum 24h volume to consider
        min_open_interest: Minimum open interest to consider
        diagnostics: Diagnostic tracker
    
    Returns:
        List of (ticker, title, yes_bids, no_bids) for markets with orderbooks.
    """
    if diagnostics is None:
        diagnostics = RunDiagnostics()
    
    # Fetch MORE markets than we need, so we can filter and select top by volume
    # Fetch 3-5x the target to ensure we get enough liquid markets
    fetch_limit = limit_markets * 4
    
    log.info(f"Fetching up to {fetch_limit} markets to select top {limit_markets} by liquidity")
    
    # Grab open markets with pagination
    all_markets = []
    cursor = None
    
    while len(all_markets) < fetch_limit:
        try:
            batch_size = min(200, fetch_limit - len(all_markets))  # Max 200 per request
            resp = kc.list_markets(status="open", limit=batch_size, cursor=cursor)
            markets = resp.get("markets") or []
            if not markets:
                break
            all_markets.extend(markets)
            
            # Check for next page
            cursor = resp.get("cursor")
            if not cursor:
                break
        except Exception as e:
            log.warning("Failed to fetch markets page: %s", e)
            break
    
    log.info(f"Fetched {len(all_markets)} total open markets")
    
    # Score and rank by liquidity (volume + open interest)
    scored_markets = []
    for m in all_markets:
        try:
            ticker = m.get('ticker', '')
            volume_24h = int(m.get('volume_24h', 0) or 0)
            open_interest = int(m.get('open_interest', 0) or 0)
            
            # Skip markets below minimum thresholds
            if volume_24h < min_volume_24h and open_interest < min_open_interest:
                continue
            
            # Liquidity score: 70% volume, 30% open interest
            # If volume is 0 everywhere, use 100% open interest
            if volume_24h == 0 and open_interest > 0:
                liquidity_score = float(open_interest)
            else:
                liquidity_score = (volume_24h * 0.7) + (open_interest * 0.3)
            
            scored_markets.append({
                'market': m,
                'ticker': ticker,
                'volume_24h': volume_24h,
                'open_interest': open_interest,
                'liquidity_score': liquidity_score
            })
        except Exception as e:
            log.warning(f"Failed to score market {m.get('ticker')}: {e}")
            continue
    
    # Sort by liquidity score (highest first)
    scored_markets.sort(key=lambda x: x['liquidity_score'], reverse=True)
    
    # Take top N
    top_markets = scored_markets[:limit_markets]
    
    # Log selection summary
    if top_markets:
        total_vol = sum(m['volume_24h'] for m in top_markets)
        total_oi = sum(m['open_interest'] for m in top_markets)
        avg_vol = total_vol / len(top_markets)
        avg_oi = total_oi / len(top_markets)
        
        log.info(f"=== Market Selection Summary ===")
        log.info(f"Total markets fetched: {len(all_markets)}")
        log.info(f"Markets after filtering: {len(scored_markets)}")
        log.info(f"Top markets selected: {len(top_markets)}")
        log.info(f"Total 24h volume: {total_vol:,}")
        log.info(f"Total open interest: {total_oi:,}")
        log.info(f"Avg 24h volume: {avg_vol:.0f}")
        log.info(f"Avg open interest: {avg_oi:.0f}")
        
        # Log top 10 markets
        log.info(f"=== Top 10 Markets by Liquidity ===")
        for i, m in enumerate(top_markets[:10], 1):
            title = m['market'].get('title', '')[:60]  # First 60 chars
            log.info(
                f"{i:2d}. {m['ticker']:45s} "
                f"vol={m['volume_24h']:6d} "
                f"oi={m['open_interest']:6d} "
                f"score={m['liquidity_score']:8.0f}"
            )
            if title:
                log.info(f"    {title}")
    
    diagnostics.markets_fetched = len(all_markets)  # Track total fetched
    
    # Now process the top markets: store metadata and fetch orderbooks
    out = []
    for scored in top_markets:
        m = scored['market']
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
        
        # Store market metadata
        session.merge(Market(
            ticker=ticker,
            title=title[:500],
            status=status,
            close_time=close_dt,
            raw_json=json.dumps(m),
            updated_at=now,
        ))
        
        # Fetch orderbook
        try:
            ob = kc.get_orderbook(ticker)
            obk = ob.get("orderbook") or {}
            yes = obk.get("yes") or []
            no = obk.get("no") or []
        except Exception as e:
            log.warning("Orderbook failed %s: %s", ticker, e)
            diagnostics.log_skip(ticker, f"orderbook_fetch_failed: {e}")
            continue
        
        # Store orderbook snapshot
        session.add(OrderbookSnapshot(
            ticker=ticker,
            ts=now,
            yes_bids_json=json.dumps(yes),
            no_bids_json=json.dumps(no),
        ))
        
        # Track orderbook quality
        if not yes and not no:
            diagnostics.markets_empty_orderbook += 1
            diagnostics.log_skip(ticker, "empty_orderbook")
        else:
            diagnostics.markets_with_orderbooks += 1
            out.append((ticker, title, yes, no))
    
    session.commit()
    log.info(f"Markets with orderbooks: {len(out)}/{len(all_markets)}")
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

def run_loop(
    *, 
    engine, 
    settings: Settings, 
    minutes: int, 
    mode: str, 
    limit_markets: int = 40,
    min_volume_24h: int = 100,
    min_open_interest: int = 50
) -> Path:
    """
    Main trading loop with enhanced diagnostics and training mode support.
    
    Modes:
    - test: demo env, validate API (no trading)
    - paper: simulate fills (no trading)
    - training: prod data, no trading (logs "would trade")
    - demo: place orders in demo env
    - prod: place orders in prod env
    """
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging to file
    import os as _os
    setup_logging(_os.getenv('CASTLE_LOG_LEVEL', 'INFO'), run_dir / 'logs.txt')
    log.info('=== Starting run %s in mode=%s, kalshi_env=%s ===', run_id, mode, settings.kalshi_env)
    log.info('Logging to %s', run_dir / 'logs.txt')
    
    # Additional file handler
    log_file = run_dir / "logs.txt"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(fh)

    # Save config
    cfg_dump = {k: str(v) for k, v in asdict(settings).items()}
    write_json(run_dir / "config.redacted.json", redact_config(cfg_dump))

    # Initialize Kalshi client with appropriate root
    kc = KalshiClient(
        root=settings.get_kalshi_root(),
        key_id=settings.kalshi_key_id or None,
        private_key_path=str(settings.kalshi_private_key_path) if settings.kalshi_private_key_path else None,
    )
    
    log.info(f"Kalshi client initialized with root: {settings.get_kalshi_root()}")

    # Initialize executors
    paper = PaperExecutor()
    live = None
    if settings.should_execute_trades():
        live = KalshiExecutor(kc)
        log.info(f"Live executor enabled for mode: {mode}")
    else:
        log.info(f"No live executor (mode={mode}, trading disabled)")

    # Initialize diagnostics
    diagnostics = RunDiagnostics()
    
    trades_rows = []
    equity_rows = []
    decisions_rows = []
    would_trade_rows = []  # For training mode

    start = _utcnow()
    end = start + dt.timedelta(minutes=minutes)

    with Session(engine) as session:
        pos = load_positions(session)
        cash_usd = float(settings.bankroll_usd)

        cycle_count = 0
        while _utcnow() < end:
            cycle_count += 1
            now = _utcnow()
            log.info(f"=== Cycle {cycle_count} at {now.isoformat()} ===")
            
            # Ingest news
            news_count = ingest_news(session, settings, now)
            if news_count > 0:
                log.info(f"Ingested {news_count} new news items")
            news = load_recent_news(session, now, settings.news_lookback_hours)

            # Ingest markets with diagnostics
            md = ingest_markets_and_orderbooks(
                session, kc, now, 
                limit_markets=limit_markets,
                min_volume_24h=min_volume_24h,
                min_open_interest=min_open_interest,
                diagnostics=diagnostics
            )

            # Compute mids for MTM
            mids_yes = {}
            from .strategy.orderbook_math import best_prices, mid_prob
            for ticker, title, yes, no in md:
                bp = best_prices(yes, no)
                pm = mid_prob(bp.best_yes_bid, bp.best_yes_ask)
                if pm is not None:
                    mids_yes[ticker] = pm

            total_expo = exposure_usd(pos)

            # Decision loop with diagnostics
            for ticker, title, yes, no in md:
                cand, skip = decide(
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
                    enable_taker_test=settings.enable_taker_test,
                )
                
                # Track skip reasons
                if skip:
                    diagnostics.log_skip(ticker, skip.reason)
                    if "spread" in skip.reason:
                        diagnostics.markets_spread_too_wide += 1
                    elif "depth" in skip.reason:
                        diagnostics.markets_insufficient_depth += 1
                    elif "edge" in skip.reason:
                        diagnostics.markets_insufficient_edge += 1
                    elif "exposure" in skip.reason:
                        diagnostics.markets_max_exposure_reached += 1
                    elif "no_best_prices" in skip.reason:
                        diagnostics.markets_no_best_prices += 1
                    continue
                
                if not cand:
                    continue

                # We have a decision!
                diagnostics.decisions_generated += 1
                
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
                    **cand.__dict__,
                })
                
                log.info(f"Decision: {cand.ticker} {cand.side} {cand.action} {cand.count}@{cand.price_cents}¢ edge={cand.edge:.3f}")

                # Execute based on mode
                if mode == "paper":
                    # Paper mode: simulate fill
                    diagnostics.orders_attempted += 1
                    filled = paper.try_fill(
                        now=now,
                        ticker=cand.ticker,
                        side=cand.side,
                        action=cand.action,
                        price_cents=cand.price_cents,
                        count=cand.count,
                        yes_bids=yes,
                        no_bids=no,
                        maker_only=settings.maker_only and not settings.enable_taker_test,
                        est_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                    )
                    if filled:
                        diagnostics.trades_filled_paper += 1
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
                        log.info(f"Paper fill: {filled.ticker} {filled.side} {filled.count}@{filled.price_cents}¢")
                    else:
                        log.info(f"Paper: no fill (maker order resting)")
                
                elif mode == "training":
                    # Training mode: log "would trade" but don't execute
                    diagnostics.orders_attempted += 1
                    would_trade_rows.append({
                        "ts": now.isoformat(),
                        "ticker": cand.ticker,
                        "side": cand.side,
                        "action": cand.action,
                        "price_cents": cand.price_cents,
                        "count": cand.count,
                        "edge": cand.edge,
                        "reason": cand.reason,
                        "mode": "training",
                        "note": "would_trade_prod_data_no_execution",
                    })
                    log.info(f"Training: would trade {cand.ticker} {cand.side} {cand.count}@{cand.price_cents}¢")
                
                elif mode == "test":
                    # Test mode: validate but don't trade
                    diagnostics.orders_attempted += 1
                    log.info(f"Test: would attempt {cand.ticker} {cand.side} {cand.count}@{cand.price_cents}¢ (no execution)")
                
                elif mode in {"demo", "prod"}:
                    # Live trading
                    assert live is not None, "Live executor should be initialized"
                    diagnostics.orders_attempted += 1
                    try:
                        res = live.submit_limit_buy(
                            now=now, 
                            ticker=cand.ticker, 
                            side=cand.side, 
                            count=cand.count, 
                            price_cents=cand.price_cents
                        )
                        diagnostics.trades_submitted_live += 1
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
                        })
                        key = (res.ticker, res.side)
                        pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), res.price_cents, res.count)
                        total_expo = exposure_usd(pos)
                        log.info(f"Live order submitted: {res.external_order_id}")
                    except Exception as e:
                        log.error(f"Failed to submit live order: {e}")

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

            # Log diagnostics summary
            log.info(f"Cycle {cycle_count} diagnostics:\n{diagnostics.summary()}")

            time.sleep(5)

    # Write artifacts
    write_csv(run_dir / "trades.csv", trades_rows)
    write_csv(run_dir / "equity.csv", equity_rows)
    write_csv(run_dir / "decisions.csv", decisions_rows)
    
    if would_trade_rows:
        write_csv(run_dir / "would_trade.csv", would_trade_rows)
        log.info(f"Training mode: {len(would_trade_rows)} would-trade entries logged")

    # Prices at end of run (for MTM proxy summaries)
    try:
        prices_end = {
            "ts": _utcnow().isoformat(),
            "yes_mid_cents": {t: int(round(p * 100)) for t, p in mids_yes.items() if p is not None},
        }
        write_json(run_dir / "prices_end.json", prices_end)
    except Exception as e:
        log.warning("Failed to write prices_end.json: %s", e)

    # Summary with diagnostics
    summary = {
        "run_id": run_id,
        "mode": mode,
        "kalshi_env": settings.kalshi_env,
        "started_at": start.isoformat(),
        "ended_at": _utcnow().isoformat(),
        "minutes": minutes,
        "cycles": cycle_count,
        "trades": len(trades_rows),
        "decisions": len(decisions_rows),
        "would_trade_entries": len(would_trade_rows),
        "diagnostics": diagnostics.to_dict(),
    }
    write_json(run_dir / "summary.json", summary)
    log.info("Run summary: %s", json.dumps(summary, indent=2))

    # Diagnostics summary
    log.info("\n=== Final Diagnostics ===")
    log.info(diagnostics.summary())
    log.info("=========================\n")

    # Extra per-run summary (trades + MTM proxy win/loss)
    try:
        write_run_summary(run_dir)
    except Exception as e:
        log.warning("Failed to write run_summary: %s", e)

    return run_dir
