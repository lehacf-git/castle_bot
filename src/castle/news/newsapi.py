from __future__ import annotations

import datetime as dt
import logging
from typing import List, Dict, Any

import requests

log = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2/everything"

def fetch_newsapi_everything(
    *,
    api_key: str,
    query: str,
    language: str = "en",
    lookback_hours: int = 24,
    page_size: int = 50,
) -> List[dict]:
    """Fetch recent articles from NewsAPI.org 'everything' endpoint.

    Returns list of {ts, title, url, summary}.
    If api_key or query is empty, returns [].
    """
    if not api_key or not query:
        return []

    now = dt.datetime.now(dt.timezone.utc)
    from_dt = now - dt.timedelta(hours=lookback_hours)

    params = {
        "q": query,
        "language": language,
        "from": from_dt.isoformat().replace("+00:00", "Z"),
        "sortBy": "publishedAt",
        "pageSize": page_size,
    }
    headers = {"X-Api-Key": api_key}

    r = requests.get(NEWSAPI_BASE, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    arts = data.get("articles") or []
    out = []
    for a in arts:
        title = (a.get("title") or "").strip()
        url = (a.get("url") or "").strip()
        desc = (a.get("description") or a.get("content") or "").strip()
        published = (a.get("publishedAt") or "").strip()
        ts = now
        if published:
            try:
                ts = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception:
                ts = now
        out.append({"ts": ts, "title": title, "url": url, "summary": desc})
    return out
