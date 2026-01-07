from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests
from tenacity import retry, wait_exponential_jitter, stop_after_attempt, retry_if_exception_type

from .auth import auth_headers, load_private_key

log = logging.getLogger(__name__)

class KalshiError(RuntimeError):
    pass

@dataclass
class KalshiClient:
    root: str
    key_id: str | None = None
    private_key_path: str | None = None
    timeout_s: int = 20

    def __post_init__(self):
        self._session = requests.Session()
        self._pk = None
        if self.key_id and self.private_key_path:
            self._pk = load_private_key(path=__import__("pathlib").Path(self.private_key_path))

    def _url(self, path: str, params: Dict[str, Any] | None = None) -> str:
        url = self.root.rstrip("/") + path
        if params:
            url = url + "?" + urlencode(params)
        return url

    @retry(
        wait=wait_exponential_jitter(initial=0.25, max=5),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((requests.RequestException, KalshiError)),
        reraise=True,
    )
    def get(self, path: str, params: Dict[str, Any] | None = None, auth: bool = False) -> Dict[str, Any]:
        url = self._url(path, params)
        headers = {}
        if auth:
            if not (self.key_id and self._pk):
                raise KalshiError("Auth requested but key_id/private_key not configured.")
            headers.update(auth_headers(key_id=self.key_id, private_key=self._pk, method="GET", path=path))
        r = self._session.get(url, headers=headers, timeout=self.timeout_s)
        if r.status_code >= 400:
            raise KalshiError(f"GET {path} failed: {r.status_code} {r.text}")
        return r.json()

    @retry(
        wait=wait_exponential_jitter(initial=0.25, max=5),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((requests.RequestException, KalshiError)),
        reraise=True,
    )
    def post(self, path: str, data: Dict[str, Any], auth: bool = True) -> Dict[str, Any]:
        url = self._url(path)
        headers = {"Content-Type": "application/json"}
        if auth:
            if not (self.key_id and self._pk):
                raise KalshiError("Auth requested but key_id/private_key not configured.")
            headers.update(auth_headers(key_id=self.key_id, private_key=self._pk, method="POST", path=path))
        r = self._session.post(url, headers=headers, json=data, timeout=self.timeout_s)
        if r.status_code >= 400:
            raise KalshiError(f"POST {path} failed: {r.status_code} {r.text}")
        return r.json()

    def list_markets(self, *, status: str = "open", limit: int = 100, cursor: str | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self.get("/markets", params=params, auth=False)

    def get_orderbook(self, ticker: str, depth: int | None = None) -> Dict[str, Any]:
        params = {"depth": depth} if depth is not None else None
        return self.get(f"/markets/{ticker}/orderbook", params=params, auth=False)

    def get_balance(self) -> Dict[str, Any]:
        return self.get("/portfolio/balance", auth=True)

    def create_order_limit_buy(self, *, ticker: str, side: str, count: int, price_cents: int, client_order_id: str) -> Dict[str, Any]:
        # API uses yes_price/no_price for limit orders depending on side.
        data: Dict[str, Any] = {
            "ticker": ticker,
            "action": "buy",
            "side": side,
            "count": int(count),
            "type": "limit",
            "client_order_id": client_order_id,
        }
        if side == "yes":
            data["yes_price"] = int(price_cents)
        elif side == "no":
            data["no_price"] = int(price_cents)
        else:
            raise ValueError("side must be 'yes' or 'no'")
        return self.post("/portfolio/orders", data, auth=True)
