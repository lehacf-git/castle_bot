"""
Training Mode Executor

Uses REAL production market data but NEVER places orders.
Logs all decisions as "would_trade" entries for analysis.

SAFETY: This executor has no methods to submit orders.
It is impossible for this executor to place real trades.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

log = logging.getLogger(__name__)


@dataclass
class WouldTrade:
    """Record of a trade that WOULD have been placed in live mode."""
    ts: dt.datetime
    ticker: str
    side: str          # yes | no
    action: str        # buy | sell
    price_cents: int
    count: int
    reason: str
    p_market: float
    p_model: float
    edge: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "ticker": self.ticker,
            "side": self.side,
            "action": self.action,
            "price_cents": self.price_cents,
            "count": self.count,
            "reason": self.reason,
            "p_market": self.p_market,
            "p_model": self.p_model,
            "edge": self.edge,
            "mode": "training",
            "executed": False,
        }


class TrainingExecutor:
    """
    Training mode executor - logs trades but NEVER executes them.
    
    SAFETY GUARANTEES:
    - No submit_order method exists
    - No connection to trading API
    - Cannot place real orders under any circumstances
    """
    
    def __init__(self):
        self.would_trades: List[WouldTrade] = []
        log.info("TrainingExecutor initialized - NO REAL TRADES WILL BE PLACED")
    
    def record_would_trade(
        self,
        *,
        now: dt.datetime,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        count: int,
        reason: str,
        p_market: float,
        p_model: float,
        edge: float,
    ) -> WouldTrade:
        """
        Record a trade that WOULD have been placed in live mode.
        
        This method ONLY logs - it does NOT execute any trades.
        """
        record = WouldTrade(
            ts=now,
            ticker=ticker,
            side=side,
            action=action,
            price_cents=price_cents,
            count=count,
            reason=reason,
            p_market=p_market,
            p_model=p_model,
            edge=edge,
        )
        
        self.would_trades.append(record)
        
        # Calculate hypothetical cost
        cost_usd = (price_cents / 100.0) * count
        
        log.info(
            f"[WOULD_TRADE] {action.upper()} {count}x {ticker} {side} "
            f"@ {price_cents}¢ (${cost_usd:.2f}) | "
            f"edge={edge:.3f} p_model={p_model:.3f}"
        )
        
        return record
    
    def get_would_trades(self) -> List[WouldTrade]:
        """Get all recorded would-trade entries."""
        return self.would_trades.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of training session."""
        if not self.would_trades:
            return {
                "total_would_trades": 0,
                "total_hypothetical_cost_usd": 0.0,
                "unique_tickers": 0,
                "avg_edge": 0.0,
            }
        
        total_cost = sum(
            (wt.price_cents / 100.0) * wt.count 
            for wt in self.would_trades
        )
        
        unique_tickers = len(set(wt.ticker for wt in self.would_trades))
        avg_edge = sum(wt.edge for wt in self.would_trades) / len(self.would_trades)
        
        return {
            "total_would_trades": len(self.would_trades),
            "total_hypothetical_cost_usd": round(total_cost, 2),
            "unique_tickers": unique_tickers,
            "avg_edge": round(avg_edge, 4),
            "by_side": {
                "yes": len([wt for wt in self.would_trades if wt.side == "yes"]),
                "no": len([wt for wt in self.would_trades if wt.side == "no"]),
            }
        }
    
    def reset(self):
        """Clear all recorded would-trades."""
        self.would_trades = []
        log.info("TrainingExecutor reset - cleared all would-trade records")
