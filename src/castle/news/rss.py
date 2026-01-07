from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable, List, Tuple

import feedparser

log = logging.getLogger(__name__)

def parse_rss(url: str) -> List[dict]:
    feed = feedparser.parse(url)
    items = []
    for e in feed.entries:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        summary = (e.get("summary") or e.get("description") or "").strip()
        # published_parsed may be None
        ts = None
        if e.get("published_parsed"):
            ts = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc)
        elif e.get("updated_parsed"):
            ts = dt.datetime(*e.updated_parsed[:6], tzinfo=dt.timezone.utc)
        else:
            ts = dt.datetime.now(dt.timezone.utc)
        items.append({"ts": ts, "title": title, "url": link, "summary": summary})
    return items
