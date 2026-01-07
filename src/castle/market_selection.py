"""
Improved market selection for Castle bot.
Selects top markets by volume and dollar value to focus on liquid, active markets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

log = logging.getLogger(__name__)


@dataclass
class MarketScore:
    """Score a market for selection priority."""
    ticker: str
    title: str
    volume_24h: int
    open_interest: int
    liquidity_score: float
    
    @classmethod
    def from_market_data(cls, market: dict) -> 'MarketScore':
        """Create score from Kalshi market data."""
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        
        # Volume metrics
        volume_24h = int(market.get('volume_24h', 0) or 0)
        open_interest = int(market.get('open_interest', 0) or 0)
        
        # Compute liquidity score
        # Weight: 70% volume, 30% open interest
        liquidity_score = (volume_24h * 0.7) + (open_interest * 0.3)
        
        return cls(
            ticker=ticker,
            title=title,
            volume_24h=volume_24h,
            open_interest=open_interest,
            liquidity_score=liquidity_score
        )


def score_and_rank_markets(
    markets: List[dict],
    *,
    min_volume_24h: int = 100,
    min_open_interest: int = 50,
    require_both: bool = False
) -> List[MarketScore]:
    """
    Score and rank markets by liquidity.
    
    Args:
        markets: Raw market data from Kalshi API
        min_volume_24h: Minimum 24h volume to include
        min_open_interest: Minimum open interest to include
        require_both: If True, require BOTH minimums; if False, require EITHER
    
    Returns:
        List of MarketScore sorted by liquidity (highest first)
    """
    scored = []
    
    for market in markets:
        try:
            score = MarketScore.from_market_data(market)
            
            # Apply filters
            volume_ok = score.volume_24h >= min_volume_24h
            oi_ok = score.open_interest >= min_open_interest
            
            if require_both:
                if not (volume_ok and oi_ok):
                    continue
            else:
                if not (volume_ok or oi_ok):
                    continue
            
            scored.append(score)
            
        except Exception as e:
            log.warning(f"Failed to score market {market.get('ticker')}: {e}")
            continue
    
    # Sort by liquidity score (highest first)
    scored.sort(key=lambda s: s.liquidity_score, reverse=True)
    
    return scored


def select_top_markets(
    markets: List[dict],
    *,
    limit: int = 100,
    min_volume_24h: int = 100,
    min_open_interest: int = 50,
    require_both: bool = False,
    series_filter: str | None = None
) -> Tuple[List[dict], dict]:
    """
    Select top N markets by liquidity.
    
    Args:
        markets: Raw market data from Kalshi API
        limit: Maximum number of markets to return
        min_volume_24h: Minimum 24h volume filter
        min_open_interest: Minimum open interest filter
        require_both: Require both filters vs either
        series_filter: Optional series ticker to filter by
    
    Returns:
        (selected_markets, selection_stats)
    """
    # Apply series filter if specified
    if series_filter:
        markets = [m for m in markets if m.get('series_ticker') == series_filter]
        log.info(f"Filtered to {len(markets)} markets in series {series_filter}")
    
    # Score and rank
    scored = score_and_rank_markets(
        markets,
        min_volume_24h=min_volume_24h,
        min_open_interest=min_open_interest,
        require_both=require_both
    )
    
    # Take top N
    top_scored = scored[:limit]
    
    # Build result
    ticker_to_market = {m['ticker']: m for m in markets}
    selected = [ticker_to_market[s.ticker] for s in top_scored if s.ticker in ticker_to_market]
    
    # Stats
    stats = {
        "total_markets_available": len(markets),
        "markets_after_filtering": len(scored),
        "markets_selected": len(selected),
        "min_liquidity_score": top_scored[-1].liquidity_score if top_scored else 0,
        "max_liquidity_score": top_scored[0].liquidity_score if top_scored else 0,
        "total_volume_24h": sum(s.volume_24h for s in top_scored),
        "total_open_interest": sum(s.open_interest for s in top_scored),
        "avg_volume_24h": sum(s.volume_24h for s in top_scored) / len(top_scored) if top_scored else 0,
        "avg_open_interest": sum(s.open_interest for s in top_scored) / len(top_scored) if top_scored else 0,
    }
    
    log.info(
        f"Selected {len(selected)}/{len(markets)} markets: "
        f"avg_volume={stats['avg_volume_24h']:.0f}, "
        f"avg_oi={stats['avg_open_interest']:.0f}, "
        f"total_volume={stats['total_volume_24h']:,}"
    )
    
    return selected, stats


def log_market_selection_summary(scored_markets: List[MarketScore], top_n: int = 10) -> None:
    """Log a summary of top markets for debugging."""
    if not scored_markets:
        log.info("No markets selected")
        return
    
    log.info(f"=== Top {top_n} Markets by Liquidity ===")
    for i, score in enumerate(scored_markets[:top_n], 1):
        log.info(
            f"{i:2d}. {score.ticker:20s} "
            f"vol={score.volume_24h:6d} "
            f"oi={score.open_interest:6d} "
            f"score={score.liquidity_score:8.0f} "
            f"| {score.title[:50]}"
        )
