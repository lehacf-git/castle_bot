from __future__ import annotations
import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List

from ..config import Settings

log = logging.getLogger(__name__)


class AutonomousTrader:
    """Fully autonomous trading system."""
    
    def __init__(
        self,
        repo_root: Path,
        settings: Settings,
        anthropic_key: str,
        openai_key: str,
        gemini_key: str,
        mode: str
    ):
        self.repo_root = repo_root
        self.settings = settings
        self.mode = mode
        
        # Multi-LLM system
        from .multi_llm_advisor import MultiLLMAdvisor
        self.llm_advisor = MultiLLMAdvisor(
            anthropic_key=anthropic_key,
            openai_key=openai_key,
            gemini_key=gemini_key
        )
        
        # News aggregation
        from ...news.news_aggregator import NewsAggregator
        self.news_aggregator = NewsAggregator(
            newsapi_key=getattr(settings, 'news_api_key', None),
            polygon_key=getattr(settings, 'polygon_key', None)
        )
        
        # Resource discovery
        from ...improve.resource_requests import ResourceRequestManager
        self.resource_manager = ResourceRequestManager(
            repo_root / "resource_requests.json"
        )
        
        # Tracking
        self.last_news_stats = {}
        self.decisions = []
    
    def run_loop(self, minutes_per_cycle: int, max_cycles: int):
        """Run the autonomous trading loop."""
        log.info("=" * 80)
        log.info("AUTONOMOUS TRADING SYSTEM")
        log.info(f"Mode: {self.mode}")
        log.info(f"Minutes per cycle: {minutes_per_cycle}")
        log.info(f"Max cycles: {max_cycles}")
        log.info("=" * 80)
        
        for cycle in range(max_cycles):
            log.info(f"\n{'='*80}")
            log.info(f"CYCLE {cycle + 1}/{max_cycles}")
            log.info(f"{'='*80}\n")
            
            try:
                # Run trading cycle
                asyncio.run(self._run_trading_cycle(minutes_per_cycle))
                
                # Run improvement cycle
                self._run_improvement_cycle(f"cycle_{cycle+1}")
                
                log.info(f"✓ Cycle {cycle + 1} complete")
            
            except KeyboardInterrupt:
                log.info("Interrupted by user")
                break
            except Exception as e:
                log.error(f"Cycle {cycle + 1} failed: {e}", exc_info=True)
        
        log.info("\n" + "="*80)
        log.info("AUTONOMOUS TRADING COMPLETE")
        log.info(f"Completed {cycle + 1} cycles")
        log.info("="*80)
    
    async def _run_trading_cycle(self, minutes: int):
        """Run one trading cycle."""
        log.info("📰 Fetching news...")
        
        try:
            all_news = await self.news_aggregator.fetch_all_news(
                lookback_hours=24,
                max_articles=200
            )
            log.info(f"   Fetched {len(all_news)} news articles")
            
            self.last_news_stats = {
                "total_articles": len(all_news),
                "sources": list(set(a.source for a in all_news)) if all_news else []
            }
        except Exception as e:
            log.warning(f"News fetch failed: {e}")
            all_news = []
            self.last_news_stats = {"total_articles": 0, "sources": []}
        
        log.info("📊 Would fetch and analyze markets here...")
        log.info("   (Market fetching + LLM consultation not yet implemented)")
        log.info(f"   This would run for {minutes} minutes")
        
        # Placeholder - in real implementation:
        # 1. Fetch markets from Kalshi
        # 2. Prioritize by time-to-close
        # 3. For each market:
        #    - Find relevant news
        #    - Get multi-LLM consensus
        #    - Execute if consensus strong
        # 4. Monitor positions
        # 5. Take profits at targets
        
        await asyncio.sleep(1)  # Placeholder
    
    def _run_improvement_cycle(self, run_id: str):
        """Run improvement cycle with resource discovery."""
        log.info("🔍 Running improvement cycle...")
        
        # Placeholder for resource discovery
        # In real implementation:
        # 1. Gather performance data
        # 2. Ask Claude to analyze
        # 3. Claude identifies missing resources
        # 4. Create resource requests
        # 5. Export for operator review
        # 6. Generate code improvements
        
        log.info("   Resource discovery not yet fully implemented")
        log.info(f"   Run ID: {run_id}")
        
        # Export empty resource requests file
        try:
            export_path = self.repo_root / "RESOURCE_REQUESTS.md"
            self.resource_manager.export_for_operator(export_path)
            log.info(f"   Exported resource requests to: {export_path}")
        except Exception as e:
            log.warning(f"Failed to export resource requests: {e}")
