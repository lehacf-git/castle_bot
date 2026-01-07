from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from ..kalshi.client import KalshiClient

@dataclass
class LiveResult:
    ts: dt.datetime
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    fee_cents: int
    external_order_id: str

class KalshiExecutor:
    def __init__(self, client: KalshiClient):
        self.client = client

    def submit_limit_buy(self, *, now: dt.datetime, ticker: str, side: str, count: int, price_cents: int) -> LiveResult:
        client_order_id = str(uuid.uuid4())
        resp = self.client.create_order_limit_buy(
            ticker=ticker,
            side=side,
            count=count,
            price_cents=price_cents,
            client_order_id=client_order_id,
        )
        order = resp.get("order") or {}
        order_id = order.get("order_id") or ""
        # Fee not returned here; treat unknown as 0 and compute later from fills if you add /portfolio/fills ingestion.
        return LiveResult(
            ts=now,
            ticker=ticker,
            side=side,
            action="buy",
            price_cents=price_cents,
            count=count,
            fee_cents=0,
            external_order_id=order_id,
        )
