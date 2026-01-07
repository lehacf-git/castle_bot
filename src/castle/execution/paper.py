from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..strategy.orderbook_math import best_prices

@dataclass
class Fill:
    ts: dt.datetime
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    fee_cents: int = 0

class PaperExecutor:
    """A conservative simulator.

    - If you submit at <= best bid (maker), assume **no fill immediately**.
    - If you submit at implied ask (taker), assume **instant fill** at that price.

    This is deliberately pessimistic for maker orders.
    """
    def __init__(self):
        pass

    def try_fill(
        self,
        *,
        now: dt.datetime,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        count: int,
        yes_bids: list[list[int]],
        no_bids: list[list[int]],
        maker_only: bool,
        est_fee_cents_per_contract: int,
    ) -> Optional[Fill]:
        bp = best_prices(yes_bids, no_bids)

        if action != "buy":
            return None

        if side == "yes":
            implied_ask = bp.best_yes_ask
            best_bid = bp.best_yes_bid
        else:
            implied_ask = bp.best_no_ask
            best_bid = bp.best_no_bid

        if implied_ask is None or best_bid is None:
            return None

        if maker_only:
            # maker orders are resting; we don't fill instantly
            return None

        # taker: fill if you cross or meet implied ask
        if price_cents >= implied_ask:
            fee = est_fee_cents_per_contract * count
            return Fill(now, ticker, side, action, implied_ask, count, fee)

        return None
