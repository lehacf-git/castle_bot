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
from .strategy.edge_strategy import decide
from .execution.paper import PaperExecutor
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
    limit_markets: int = 100
) -> tuple[list[tuple[str, str, list, list]], int, int]:
    """
    Returns: (market_data, markets_scanned, markets_with_orderbooks)
    """
    # Grab open markets
    resp = kc.list_markets(status="open", limit=limit_markets)
    markets = resp.get("markets") or []
    
    markets_scanned = len(markets)
    markets_with_books = 0
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
            
            # Count markets with non-empty orderbooks
            if yes or no:
                markets_with_books += 1
            
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
    return out, markets_scanned, markets_with_books

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

class DecisionCooldown:
    """Track recent decisions to prevent churn."""
    def __init__(self, cooldown_seconds: int = 60):
        self.cooldown_seconds = cooldown_seconds
        self.last_decision: dict[str, dt.datetime] = {}
    
    def can_decide(self, ticker: str, now: dt.datetime) -> bool:
        if ticker not in self.last_decision:
            return True
        elapsed = (now - self.last_decision[ticker]).total_seconds()
        return elapsed >= self.cooldown_seconds
    
    def record_decision(self, ticker: str, now: dt.datetime):
        self.last_decision[ticker] = now

def run_loop(
    *,
    engine,
    settings: Settings,
    minutes: int,
    mode: str,
    limit_markets: int = 100
) -> Path:
    """
    Enhanced run loop with:
    - Training mode support (prod data, no trading)
    - Comprehensive diagnostics (skip reasons, counters)
    - Decision cooldown to prevent churn
    """
    
    # Mode validation
    valid_modes = {"test", "paper", "training", "demo", "prod"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of: {valid_modes}")
    
    # Determine Kalshi environment
    if mode in {"test", "demo"}:
        env = "demo"
    elif mode in {"training", "prod"}:
        env = "prod"
    else:  # paper
        env = settings.kalshi_env  # Use config default for paper
    
    # Determine if we can trade
    can_trade = mode in {"demo", "prod"}
    
    log.info(f"Starting run loop: mode={mode}, env={env}, can_trade={can_trade}")
    
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging to file
    log_file = run_dir / "logs.txt"
    setup_logging(settings.log_level, log_file)
    log.info(f'Run started: mode={mode}, env={env}, run_id={run_id}')

    # Configure file logging
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(fh)

    cfg_dump = {k: str(v) for k, v in asdict(settings).items()}
    write_json(run_dir / "config.redacted.json", redact_config(cfg_dump))

    # Select appropriate base URL
    base_url = settings.kalshi_prod_root if env == "prod" else settings.kalshi_demo_root
    
    kc = KalshiClient(
        root=base_url,
        key_id=settings.kalshi_key_id or None,
        private_key_path=str(settings.kalshi_private_key_path) if settings.kalshi_private_key_path else None,
    )

    paper = PaperExecutor()
    live = KalshiExecutor(kc) if can_trade else None

    trades_rows = []
    equity_rows = []
    decisions_rows = []
    skip_rows = []

    # Diagnostics
    cooldown = DecisionCooldown(settings.decision_cooldown_seconds)
    skip_reasons = Counter()
    total_markets_scanned = 0
    total_markets_with_books = 0

    start = _utcnow()
    end = start + dt.timedelta(minutes=minutes)

    with Session(engine) as session:
        pos = load_positions(session)
        cash_usd = float(settings.bankroll_usd)

        while _utcnow() < end:
            now = _utcnow()
            
            # Ingest news
            news_count = ingest_news(session, settings, now)
            if news_count > 0:
                log.info(f"Ingested {news_count} new news items")
            
            news = load_recent_news(session, now, settings.news_lookback_hours)

            # Ingest markets and orderbooks
            md, scanned, with_books = ingest_markets_and_orderbooks(
                session, kc, now, limit_markets=limit_markets
            )
            total_markets_scanned += scanned
            total_markets_with_books += with_books
            
            log.info(
                f"Market scan: {scanned} markets scanned, "
                f"{with_books} with orderbooks, "
                f"{len(md)} with valid data"
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

            decisions_this_cycle = 0
            skips_this_cycle = 0
            
            for ticker, title, yes, no in md:
                # Check cooldown
                if not cooldown.can_decide(ticker, now):
                    skip_reasons["cooldown"] += 1
                    skips_this_cycle += 1
                    continue
                
                # Decide
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
                
                if skip:
                    skip_reasons[skip.reason] += 1
                    skips_this_cycle += 1
                    skip_rows.append({
                        "ts": now.isoformat(),
                        "ticker": skip.ticker,
                        "reason": skip.reason,
                        "details": json.dumps(skip.details),
                    })
                    continue
                
                if not cand:
                    continue
                
                # Record decision
                cooldown.record_decision(ticker, now)
                decisions_this_cycle += 1

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
                
                log.info(
                    f"Decision: {cand.ticker} {cand.side} @ {cand.price_cents}¢ "
                    f"× {cand.count} (edge={cand.edge:.3f})"
                )

                # Execution
                filled = None
                
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
                        maker_only=settings.maker_only and not settings.enable_taker_test,
                        est_fee_cents_per_contract=settings.est_taker_fee_cents_per_contract,
                    )
                    if filled:
                        log.info(f"Paper fill: {filled.ticker} {filled.side} @ {filled.price_cents}¢")
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
                    # Training mode: log "would trade" but don't execute
                    log.info(
                        f"Training mode - would trade: {cand.ticker} {cand.side} "
                        f"@ {cand.price_cents}¢ × {cand.count}"
                    )
                    trades_rows.append({
                        "ts": now.isoformat(),
                        "ticker": cand.ticker,
                        "side": cand.side,
                        "action": cand.action,
                        "price_cents": cand.price_cents,
                        "count": cand.count,
                        "fee_cents": 0,
                        "mode": "training",
                        "external_order_id": "would_trade",
                    })

                elif mode == "test":
                    # Test mode: validate API but don't trade
                    log.info(f"Test mode - validating API access for {cand.ticker}")
                    # Could add portfolio/balance checks here
                    
                elif can_trade:  # demo or prod
                    # Live trading
                    assert live is not None
                    log.info(f"Submitting live order: {cand.ticker} {cand.side} @ {cand.price_cents}¢")
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
                    })
                    key = (res.ticker, res.side)
                    pos[key] = apply_buy(pos.get(key, PositionState(0, 0.0)), res.price_cents, res.count)
                    total_expo = exposure_usd(pos)

            # Equity snapshot
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
            
            log.info(
                f"Cycle complete: {decisions_this_cycle} decisions, "
                f"{skips_this_cycle} skips, "
                f"{len(trades_rows)} total trades"
            )

            time.sleep(5)

    # Write artifacts
    write_csv(run_dir / "trades.csv", trades_rows)
    write_csv(run_dir / "equity.csv", equity_rows)
    write_csv(run_dir / "decisions.csv", decisions_rows)
    write_csv(run_dir / "skips.csv", skip_rows)

    # Diagnostics summary
    diagnostics = {
        "markets_scanned": total_markets_scanned,
        "markets_with_orderbooks": total_markets_with_books,
        "skip_reasons": dict(skip_reasons.most_common(10)),
        "total_skips": sum(skip_reasons.values()),
        "decisions_generated": len(decisions_rows),
        "trades_executed": len([t for t in trades_rows if t.get("mode") != "training"]),
        "training_would_trades": len([t for t in trades_rows if t.get("mode") == "training"]),
    }
    write_json(run_dir / "diagnostics.json", diagnostics)
    
    log.info(f"Diagnostics: {json.dumps(diagnostics, indent=2)}")

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
        "env": env,
        "started_at": start.isoformat(),
        "ended_at": _utcnow().isoformat(),
        "minutes": minutes,
        "trades": len([t for t in trades_rows if t.get("mode") != "training"]),
        "decisions": len(decisions_rows),
        "diagnostics": diagnostics,
    }
    write_json(run_dir / "summary.json", summary)
    log.info("Run summary: %s", summary)

    # Extra per-run summary
    try:
        write_run_summary(run_dir)
    except Exception as e:
        log.warning("Failed to write run_summary: %s", e)

    return run_dir
