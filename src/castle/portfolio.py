from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Tuple

@dataclass
class PositionState:
    qty: int
    avg_price_cents: float

def apply_buy(pos: PositionState, price_cents: int, count: int) -> PositionState:
    if count <= 0:
        return pos
    new_qty = pos.qty + count
    new_avg = (pos.avg_price_cents * pos.qty + price_cents * count) / max(1, new_qty)
    return PositionState(qty=new_qty, avg_price_cents=new_avg)

def mark_to_market_usd(positions: dict[tuple[str, str], PositionState], mids_yes_prob: dict[str, float]) -> float:
    """Approximate MTM using mid YES probability. NO is valued at (1 - p_yes)."""
    total_cents = 0.0
    for (ticker, side), p in positions.items():
        py = mids_yes_prob.get(ticker)
        if py is None:
            continue
        if side == "yes":
            value_cents = 100.0 * py
        else:
            value_cents = 100.0 * (1.0 - py)
        total_cents += p.qty * value_cents
    return total_cents / 100.0
