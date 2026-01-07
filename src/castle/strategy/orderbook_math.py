from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass(frozen=True)
class BestPrices:
    best_yes_bid: Optional[int]
    best_yes_ask: Optional[int]  # implied from NO bids
    best_no_bid: Optional[int]
    best_no_ask: Optional[int]   # implied from YES bids

def best_prices(yes_bids: List[List[int]], no_bids: List[List[int]]) -> BestPrices:
    # Arrays are ascending; best bid is last element if any.
    best_yes_bid = yes_bids[-1][0] if yes_bids else None
    best_no_bid = no_bids[-1][0] if no_bids else None
    best_yes_ask = (100 - best_no_bid) if best_no_bid is not None else None
    best_no_ask = (100 - best_yes_bid) if best_yes_bid is not None else None
    return BestPrices(best_yes_bid, best_yes_ask, best_no_bid, best_no_ask)

def mid_prob(best_yes_bid: int | None, best_yes_ask: int | None) -> float | None:
    if best_yes_bid is None or best_yes_ask is None:
        return None
    mid_cents = (best_yes_bid + best_yes_ask) / 2.0
    return mid_cents / 100.0

def spread_cents(best_yes_bid: int | None, best_yes_ask: int | None) -> int | None:
    if best_yes_bid is None or best_yes_ask is None:
        return None
    return int(best_yes_ask - best_yes_bid)

def depth_within(yes_bids: List[List[int]], no_bids: List[List[int]], depth_cents: int = 5) -> tuple[int, int]:
    yes_depth = 0
    no_depth = 0
    if yes_bids:
        best_yes = yes_bids[-1][0]
        for price, qty in reversed(yes_bids):
            if best_yes - price <= depth_cents:
                yes_depth += qty
            else:
                break
    if no_bids:
        best_no = no_bids[-1][0]
        for price, qty in reversed(no_bids):
            if best_no - price <= depth_cents:
                no_depth += qty
            else:
                break
    return yes_depth, no_depth
