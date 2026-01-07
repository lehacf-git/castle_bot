from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict
import logging

log = logging.getLogger(__name__)


@dataclass
class RunDiagnostics:
    """Track diagnostic counters for a run to understand why decisions aren't being made."""
    
    markets_fetched: int = 0
    markets_with_orderbooks: int = 0
    markets_empty_orderbook: int = 0
    markets_no_best_prices: int = 0
    markets_spread_too_wide: int = 0
    markets_insufficient_depth: int = 0
    markets_no_edge: int = 0
    markets_insufficient_edge: int = 0
    markets_max_exposure_reached: int = 0
    markets_insufficient_liquidity: int = 0
    decisions_generated: int = 0
    orders_attempted: int = 0
    trades_filled_paper: int = 0
    trades_submitted_live: int = 0
    
    # Skip reason details (ticker -> reason)
    skip_reasons: Dict[str, str] = field(default_factory=dict)
    
    def log_skip(self, ticker: str, reason: str) -> None:
        """Log why a market was skipped."""
        self.skip_reasons[ticker] = reason
        log.debug(f"Skip {ticker}: {reason}")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "markets_fetched": self.markets_fetched,
            "markets_with_orderbooks": self.markets_with_orderbooks,
            "markets_empty_orderbook": self.markets_empty_orderbook,
            "markets_no_best_prices": self.markets_no_best_prices,
            "markets_spread_too_wide": self.markets_spread_too_wide,
            "markets_insufficient_depth": self.markets_insufficient_depth,
            "markets_no_edge": self.markets_no_edge,
            "markets_insufficient_edge": self.markets_insufficient_edge,
            "markets_max_exposure_reached": self.markets_max_exposure_reached,
            "markets_insufficient_liquidity": self.markets_insufficient_liquidity,
            "decisions_generated": self.decisions_generated,
            "orders_attempted": self.orders_attempted,
            "trades_filled_paper": self.trades_filled_paper,
            "trades_submitted_live": self.trades_submitted_live,
            "skip_reasons_sample": dict(list(self.skip_reasons.items())[:20]),  # Sample to avoid huge output
        }
    
    def summary(self) -> str:
        """Get a human-readable summary."""
        lines = [
            f"Markets fetched: {self.markets_fetched}",
            f"Markets with orderbooks: {self.markets_with_orderbooks}",
            f"Decisions generated: {self.decisions_generated}",
            f"Orders attempted: {self.orders_attempted}",
        ]
        
        if self.markets_empty_orderbook > 0:
            lines.append(f"  ↳ Empty orderbooks: {self.markets_empty_orderbook}")
        if self.markets_no_best_prices > 0:
            lines.append(f"  ↳ No best prices: {self.markets_no_best_prices}")
        if self.markets_spread_too_wide > 0:
            lines.append(f"  ↳ Spread too wide: {self.markets_spread_too_wide}")
        if self.markets_insufficient_depth > 0:
            lines.append(f"  ↳ Insufficient depth: {self.markets_insufficient_depth}")
        if self.markets_insufficient_edge > 0:
            lines.append(f"  ↳ Insufficient edge: {self.markets_insufficient_edge}")
        if self.markets_max_exposure_reached > 0:
            lines.append(f"  ↳ Max exposure reached: {self.markets_max_exposure_reached}")
        
        if self.trades_filled_paper > 0:
            lines.append(f"Trades filled (paper): {self.trades_filled_paper}")
        if self.trades_submitted_live > 0:
            lines.append(f"Trades submitted (live): {self.trades_submitted_live}")
        
        return "\n".join(lines)
