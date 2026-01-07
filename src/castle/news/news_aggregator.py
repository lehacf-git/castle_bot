from __future__ import annotations
import asyncio
import datetime as dt
import hashlib
import logging
from dataclasses import dataclass
from typing import List, Dict

log = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """A single news article."""
    source: str
    title: str
    url: str
    summary: str
    published: dt.datetime
    content_hash: str
    relevance_score: float = 0.0
    sentiment: str = "neutral"
    keywords: List[str] = None


class NewsAggregator:
    """Aggregate news from multiple sources."""
    
    def __init__(
        self,
        newsapi_key: str | None = None,
        polygon_key: str | None = None
    ):
        self.newsapi_key = newsapi_key
        self.polygon_key = polygon_key
        self.cache: Dict[str, NewsArticle] = {}
        
        # RSS feeds (free, no API key required)
        self.rss_feeds = [
            "http://feeds.reuters.com/reuters/topNews",
            "http://rss.cnn.com/rss/cnn_topstories.rss",
            "https://www.espn.com/espn/rss/news",
        ]
    
    async def fetch_all_news(
        self,
        lookback_hours: int = 24,
        max_articles: int = 200
    ) -> List[NewsArticle]:
        """Fetch news from all available sources."""
        try:
            import feedparser
        except ImportError:
            log.warning("feedparser not installed - news disabled")
            return []
        
        # For now, just fetch RSS feeds
        articles = await self._fetch_rss_feeds(lookback_hours)
        
        # Deduplicate
        unique = {}
        for article in articles:
            if article.content_hash not in unique:
                unique[article.content_hash] = article
        
        articles = list(unique.values())
        articles.sort(key=lambda a: a.published, reverse=True)
        
        return articles[:max_articles]
    
    async def _fetch_rss_feeds(self, lookback_hours: int) -> List[NewsArticle]:
        """Fetch from RSS feeds."""
        try:
            import feedparser
        except ImportError:
            return []
        
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lookback_hours)
        articles = []
        
        for feed_url in self.rss_feeds:
            try:
                feed = await asyncio.to_thread(feedparser.parse, feed_url)
                
                for entry in feed.entries:
                    # Parse published time
                    published = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        published = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc)
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        published = dt.datetime(*entry.updated_parsed[:6], tzinfo=dt.timezone.utc)
                    else:
                        published = dt.datetime.now(dt.timezone.utc)
                    
                    if published < cutoff:
                        continue
                    
                    title = entry.get('title', '')
                    summary = entry.get('summary', entry.get('description', ''))
                    url = entry.get('link', '')
                    
                    content_hash = hashlib.md5(f"{title}{summary}".encode()).hexdigest()
                    
                    articles.append(NewsArticle(
                        source=feed_url,
                        title=title,
                        url=url,
                        summary=summary,
                        published=published,
                        content_hash=content_hash
                    ))
            
            except Exception as e:
                log.warning(f"RSS feed {feed_url} failed: {e}")
        
        return articles


class NewsMarketMatcher:
    """Match news articles to prediction markets."""
    
    @staticmethod
    def find_relevant_news(
        market_title: str,
        market_ticker: str,
        all_news: List[NewsArticle],
        max_articles: int = 10
    ) -> List[NewsArticle]:
        """Find news relevant to a specific market."""
        import re
        
        # Extract keywords from market title
        words = re.findall(r'\b[A-Z][a-z]+\b|\b\w{4,}\b', market_title)
        market_keywords = set(w.lower() for w in words)
        
        if not market_keywords:
            return []
        
        # Score each article by relevance
        scored = []
        for article in all_news:
            text = f"{article.title} {article.summary}".lower()
            
            matches = sum(1 for kw in market_keywords if kw in text)
            
            if matches > 0:
                article.relevance_score = matches / len(market_keywords)
                scored.append(article)
        
        # Sort by relevance and recency
        now = dt.datetime.now(dt.timezone.utc)
        scored.sort(
            key=lambda a: (
                a.relevance_score * 10 + 
                (1.0 / max(1, (now - a.published).total_seconds() / 3600))
            ),
            reverse=True
        )
        
        return scored[:max_articles]
