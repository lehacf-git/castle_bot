# src/castle/improve/claude_resource_discovery.py

from __future__ import annotations
import anthropic
import json
import logging
from typing import Dict, List
from .resource_requests import ResourceRequestManager, ResourceType, Priority

log = logging.getLogger(__name__)


class ClaudeResourceDiscovery:
    """Claude analyzes performance and automatically identifies needed resources."""
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
    
    def analyze_and_discover_resources(
        self,
        *,
        run_id: str,
        run_metrics: Dict,
        trade_history: List[Dict],
        llm_performance: Dict,
        news_coverage: Dict,
        current_capabilities: List[str]
    ) -> List[Dict]:
        """
        Claude analyzes performance and identifies missing resources.
        
        Returns list of resource request specifications.
        """
        
        prompt = f"""You are analyzing an autonomous trading bot to identify missing resources that would significantly improve performance.

CURRENT RUN: {run_id}

PERFORMANCE METRICS:
{json.dumps(run_metrics, indent=2)}

TRADE SAMPLE (last 30):
{json.dumps(trade_history[-30:], indent=2)}

LLM PERFORMANCE COMPARISON:
{json.dumps(llm_performance, indent=2)}

NEWS COVERAGE STATISTICS:
{json.dumps(news_coverage, indent=2)}

CURRENT CAPABILITIES:
{chr(10).join('- ' + c for c in current_capabilities)}

---

TASK: Identify missing resources/data sources that would SIGNIFICANTLY improve trading performance.

Focus on data gaps that caused:
1. Lost trades (skipped opportunities due to missing data)
2. Wrong predictions (LLMs lacked key information)
3. Late entries (information arrived too slowly)
4. Poor exits (couldn't monitor changing conditions)

For each identified resource need:

- **Evidence Required:** Show specific examples from trade history
- **Impact Required:** Must improve performance by >10% (be conservative)
- **Cost-Benefit:** Consider implementation cost vs expected value

Resource types to consider:
- **API Access:** Real-time data feeds (sports stats, weather, social sentiment, odds)
- **Data Sources:** New information streams we don't have
- **Libraries:** Python packages enabling new analysis
- **Infrastructure:** Faster execution, more storage, etc.
- **Features:** New capabilities (options pricing, portfolio optimization)

Return JSON array (ONLY include resources with strong evidence):
[
  {{
    "resource_type": "api|data_source|library|infrastructure|feature",
    "priority": "critical|high|medium|low",
    "title": "Short descriptive title",
    "description": "Detailed description of what's needed",
    "justification": "Why we need this (with evidence from trades)",
    "analysis": "Specific analysis from this run that revealed the need",
    "expected_improvement": "Quantified expected improvement (+X% win rate, +$Y profit, enable Z markets)",
    "cost_estimate": "Rough monthly cost or 'Unknown'",
    "implementation_notes": "How to implement (APIs, libraries, code changes)",
    "alternatives": ["alternative approach 1", "alternative approach 2"]
  }}
]

**CRITICAL RULES:**
- Only suggest resources with concrete evidence from the data above
- Be conservative on expected improvements (under-promise)
- Prioritize by ROI (improvement / cost)
- Empty array [] is acceptable if no strong needs identified
"""
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            text = response.content[0].text
            
            # Parse JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            requests = json.loads(text.strip())
            return requests if isinstance(requests, list) else []
        
        except Exception as e:
            log.error(f"Resource discovery failed: {e}")
            return []
    
    def create_requests_from_analysis(
        self,
        analysis_results: List[Dict],
        request_manager: ResourceRequestManager,
        run_id: str
    ) -> List[str]:
        """Create resource requests from Claude's analysis."""
        created_ids = []
        
        for req_data in analysis_results:
            try:
                # Map string values to enums
                resource_type = ResourceType(req_data['resource_type'])
                priority = Priority(req_data['priority'])
                
                request = request_manager.create_request(
                    resource_type=resource_type,
                    priority=priority,
                    title=req_data['title'],
                    description=req_data['description'],
                    justification=req_data['justification'],
                    analysis=req_data['analysis'],
                    expected_improvement=req_data['expected_improvement'],
                    discovered_during_run=run_id,
                    cost_estimate=req_data.get('cost_estimate', 'Unknown'),
                    implementation_notes=req_data.get('implementation_notes', ''),
                    alternatives=req_data.get('alternatives', [])
                )
                
                created_ids.append(request.request_id)
                log.info(f"Created resource request: {request.title} ({request.priority.value})")
            
            except Exception as e:
                log.error(f"Failed to create request from analysis: {e}")
        
        return created_ids
