from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from .orderbook_math import best_prices, mid_prob, spread_cents, depth_within
from .news_signal import aggregate_news_signal

@dataclass(frozen=True)
class DecisionCandidate:
    ticker: str
    side: str            # yes|no
    action: str          # buy
    price_cents: int
    count: int
    p_market: float
    p_model: float
    edge: float
    reason: str

@dataclass(frozen=True)
class SkipReason:
    """Represents why a market was skipped."""
    ticker: str
    reason: str
    details: str = ""

def decide(
    *,
    ticker: str,
    title: str,
    yes_bids: list[list[int]],
    no_bids: list[list[int]],
    now: dt.datetime,
    news_headlines: list[tuple[dt.datetime, str]],
    min_edge_prob: float,
    max_spread_cents: int,
    min_depth_contracts: int,
    bankroll_usd: float,
    max_risk_per_market_usd: float,
    max_total_exposure_usd: float,
    current_total_exposure_usd: float,
    maker_only: bool,
    est_taker_fee_cents_per_contract: int,
    enable_taker_test: bool = False,
) -> tuple[Optional[DecisionCandidate], Optional[SkipReason]]:
    """
    Evaluate a market and return either a decision or a skip reason.
    
    Returns: (decision, skip_reason) where exactly one is None.
    """
    
    # Check for empty orderbook
    if not yes_bids and not no_bids:
        return None, SkipReason(ticker, "empty_orderbook", "Both yes_bids and no_bids are empty")
    
    bp = best_prices(yes_bids, no_bids)
    
    # Check for missing best prices
    if bp.best_yes_bid is None or bp.best_yes_ask is None:
        return None, SkipReason(ticker, "no_best_prices", f"yes_bid={bp.best_yes_bid}, yes_ask={bp.best_yes_ask}")
    
    sp = spread_cents(bp.best_yes_bid, bp.best_yes_ask)
    if sp is None:
        return None, SkipReason(ticker, "no_spread", "Could not compute spread")
    
    if sp > max_spread_cents:
        return None, SkipReason(ticker, "spread_too_wide", f"spread={sp}¢ > max={max_spread_cents}¢")

    yes_depth, no_depth = depth_within(yes_bids, no_bids, depth_cents=5)
    max_depth = max(yes_depth, no_depth)
    if max_depth < min_depth_contracts:
        return None, SkipReason(ticker, "insufficient_depth", 
                                f"max_depth={max_depth} < min={min_depth_contracts}")

    pm = mid_prob(bp.best_yes_bid, bp.best_yes_ask)
    if pm is None:
        return None, SkipReason(ticker, "no_mid_prob", "Could not compute mid probability")

    # News -> small tilt around market mid.
    ns = aggregate_news_signal(title, news_headlines, now, lookback_hours=24)
    # tilt magnitude capped at 8 percentage points, scaled by match weight
    tilt = 0.08 * ns.score * min(1.0, ns.weight)
    p_model = min(0.99, max(0.01, pm + tilt))

    # Choose side based on p_model vs p_market
    edge = p_model - pm
    if abs(edge) < min_edge_prob:
        return None, SkipReason(ticker, "insufficient_edge", 
                                f"abs(edge)={abs(edge):.4f} < min={min_edge_prob:.4f}")

    # Fee cushion (very rough): require extra edge if taking.
    # In cents, fee drag for taker effectively reduces expected value. We'll map cents to prob.
    fee_prob = est_taker_fee_cents_per_contract / 100.0
    
    # Determine if we're testing taker logic
    effective_maker_only = maker_only and not enable_taker_test
    
    if not effective_maker_only:
        if abs(edge) < (min_edge_prob + fee_prob):
            return None, SkipReason(ticker, "insufficient_edge_after_fees",
                                    f"abs(edge)={abs(edge):.4f} < min+fee={min_edge_prob+fee_prob:.4f}")

    side = "yes" if edge > 0 else "no"

    # Price selection:
    # Maker-only => bid at best bid for that side.
    # Otherwise => cross implied ask (taker) for stronger edge.
    if effective_maker_only:
        if side == "yes":
            if bp.best_yes_bid is None:
                return None, SkipReason(ticker, "no_yes_bid", "Cannot place maker order, no yes bid")
            price = bp.best_yes_bid
        else:
            if bp.best_no_bid is None:
                return None, SkipReason(ticker, "no_no_bid", "Cannot place maker order, no no bid")
            price = bp.best_no_bid
    else:
        if side == "yes":
            if bp.best_yes_ask is None:
                return None, SkipReason(ticker, "no_yes_ask", "Cannot cross, no yes ask")
            price = bp.best_yes_ask
        else:
            # buying NO crosses NO ask, which is implied from YES bid
            if bp.best_no_ask is None:
                return None, SkipReason(ticker, "no_no_ask", "Cannot cross, no no ask")
            price = bp.best_no_ask

    # Bet sizing: simple capped fractional-kelly-ish based on edge magnitude.
    max_risk = min(max_risk_per_market_usd, max(0.0, max_total_exposure_usd - current_total_exposure_usd))
    if max_risk <= 0:
        return None, SkipReason(ticker, "max_exposure_reached",
                                f"current={current_total_exposure_usd:.2f} >= max={max_total_exposure_usd:.2f}")

    # worst-case risk for buying: price_cents per contract (USD = cents/100)
    cost_per_contract = price / 100.0
    if cost_per_contract <= 0:
        return None, SkipReason(ticker, "invalid_price", f"price={price}¢ invalid")

    # base size proportional to |edge|; cap to max_risk.
    target_usd = max_risk * min(1.0, abs(edge) / 0.10)  # full size at 10pp edge
    count = int(max(1, target_usd / cost_per_contract))
    count = max(1, min(count, int(max_risk / cost_per_contract)))

    mode_note = "(taker_test)" if enable_taker_test else ""
    reason = (f"pm={pm:.3f} model={p_model:.3f} edge={edge:.3f} spread={sp}¢ "
              f"ns=({ns.score:.2f},{ns.weight:.2f}) {ns.reason} {mode_note}")

    decision = DecisionCandidate(
        ticker=ticker,
        side=side,
        action="buy",
        price_cents=int(price),
        count=int(count),
        p_market=float(pm),
        p_model=float(p_model),
        edge=float(edge),
        reason=reason,
    )
    
    return decision, None
