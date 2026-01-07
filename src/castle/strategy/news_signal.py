from __future__ import annotations

import math
import re
import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List, Tuple

_WORD = re.compile(r"[A-Za-z0-9]+")

POS = {"beat","surge","rise","up","gain","record","strong","approval","win","wins","leading","ahead","bullish","positive"}
NEG = {"fall","down","drop","plunge","weak","miss","loss","loses","behind","bearish","negative","recession","inflation","lawsuit","crisis"}

def tokenize(s: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD.finditer(s or "") if len(m.group(0)) >= 3}

def sentiment_score(text: str) -> float:
    toks = tokenize(text)
    if not toks:
        return 0.0
    pos = sum(1 for t in toks if t in POS)
    neg = sum(1 for t in toks if t in NEG)
    return (pos - neg) / max(5, (pos + neg))

def match_strength(market_title: str, headline: str) -> float:
    mt = tokenize(market_title)
    ht = tokenize(headline)
    if not mt or not ht:
        return 0.0
    inter = len(mt & ht)
    return inter / max(3, len(mt))  # heuristic

@dataclass(frozen=True)
class NewsSignal:
    score: float         # [-1, +1] roughly
    weight: float        # [0, 1]
    reason: str

def aggregate_news_signal(
    market_title: str,
    news_items: List[tuple[dt.datetime, str]],
    now: dt.datetime,
    lookback_hours: int = 24,
) -> NewsSignal:
    lookback = dt.timedelta(hours=lookback_hours)
    total = 0.0
    wsum = 0.0
    best_reason = ""
    for ts, headline in news_items:
        age = now - ts
        if age < dt.timedelta(0) or age > lookback:
            continue
        ms = match_strength(market_title, headline)
        if ms <= 0:
            continue
        s = sentiment_score(headline)
        # recency decay: half-life ~6 hours
        rec_w = math.exp(-age.total_seconds() / (6 * 3600))
        w = ms * rec_w
        total += s * w
        wsum += w
        if w > 0.25 and not best_reason:
            best_reason = f"news='{headline[:120]}' ms={ms:.2f} s={s:.2f}"
    if wsum == 0:
        return NewsSignal(score=0.0, weight=0.0, reason="no relevant news")
    score = max(-1.0, min(1.0, total / wsum))
    weight = max(0.0, min(1.0, wsum))
    return NewsSignal(score=score, weight=weight, reason=best_reason or "news matched")
