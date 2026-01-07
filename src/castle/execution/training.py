# NEW FILE: src/castle/execution/training.py
# Training mode: logs "would trade" decisions without placing orders

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

@dataclass
class TrainingResult:
    """Represents a "would have traded" entry for training mode."""
    ts: dt.datetime
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    fee_cents: int
    mode: str = "training"
    external_order_id: str = "TRAINING_WOULD_PLACE"

class TrainingExecutor:
    """
    Training mode executor.
    
    Uses production market data but NEVER places orders.
    All "trades" are logged as "would place" entries.
    """
    
    def __init__(self):
        pass
    
    def would_place_order(
        self,
        *,
        now: dt.datetime,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        count: int,
        est_fee_cents_per_contract: int,
    ) -> TrainingResult:
        """
        Log a "would place order" entry.
        
        This does NOT interact with any API - it only creates a log entry
        for later analysis.
        """
        fee = est_fee_cents_per_contract * count
        
        return TrainingResult(
            ts=now,
            ticker=ticker,
            side=side,
            action=action,
            price_cents=price_cents,
            count=count,
            fee_cents=fee,
            mode="training",
            external_order_id="TRAINING_WOULD_PLACE",
        )
