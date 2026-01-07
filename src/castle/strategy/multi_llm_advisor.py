from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List
import statistics

log = logging.getLogger(__name__)


@dataclass
class LLMPrediction:
    """Prediction from a single LLM."""
    llm_name: str
    probability: float
    confidence: float
    reasoning: str
    suggested_size: int
    suggested_action: str


@dataclass
class ConsensusDecision:
    """Consensus from all LLMs."""
    ticker: str
    consensus_prob: float
    consensus_action: str
    consensus_size: int
    agreement_level: float
    predictions: List[LLMPrediction]
    reasoning: str


class MultiLLMAdvisor:
    """Consult multiple LLMs for trading decisions."""
    
    def __init__(
        self,
        anthropic_key: str,
        openai_key: str,
        gemini_key: str
    ):
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.gemini_key = gemini_key
        
        # Initialize clients
        try:
            import anthropic
            self.claude = anthropic.Anthropic(api_key=anthropic_key)
            self.claude_model = "claude-sonnet-4-20250514"
        except ImportError:
            log.warning("anthropic package not installed")
            self.claude = None
        
        try:
            import openai
            self.openai = openai.OpenAI(api_key=openai_key)
            self.openai_model = "gpt-4o"
        except ImportError:
            log.warning("openai package not installed")
            self.openai = None
        
        try:
            from google import generativeai as genai
            genai.configure(api_key=gemini_key)
            self.gemini = genai.GenerativeModel('gemini-1.5-flash')
        except ImportError:
            log.warning("google-generativeai package not installed")
            self.gemini = None
    
    async def get_consensus_with_news(
        self,
        ticker: str,
        market_info: Dict,
        orderbook: Dict,
        news_articles: List
    ) -> ConsensusDecision:
        """Get consensus prediction from all available LLMs with news context."""
        
        # Query all available LLMs in parallel
        tasks = []
        
        if self.claude:
            tasks.append(self.ask_claude_with_news(market_info, orderbook, news_articles))
        if self.openai:
            tasks.append(self.ask_gpt_with_news(market_info, orderbook, news_articles))
        if self.gemini:
            tasks.append(self.ask_gemini_with_news(market_info, orderbook, news_articles))
        
        if not tasks:
            # No LLMs available - skip
            return ConsensusDecision(
                ticker=ticker,
                consensus_prob=0.5,
                consensus_action="skip",
                consensus_size=0,
                agreement_level=0.0,
                predictions=[],
                reasoning="No LLM APIs available"
            )
        
        predictions = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out errors
        valid_predictions = [p for p in predictions if isinstance(p, LLMPrediction) and p.confidence > 0]
        
        if len(valid_predictions) < 1:
            return ConsensusDecision(
                ticker=ticker,
                consensus_prob=0.5,
                consensus_action="skip",
                consensus_size=0,
                agreement_level=0.0,
                predictions=[],
                reasoning="All LLM queries failed"
            )
        
        # Calculate weighted consensus
        total_weight = sum(p.confidence for p in valid_predictions)
        consensus_prob = sum(p.probability * p.confidence for p in valid_predictions) / total_weight
        
        # Consensus action (majority vote weighted by confidence)
        action_votes = {}
        for p in valid_predictions:
            action_votes[p.suggested_action] = action_votes.get(p.suggested_action, 0) + p.confidence
        consensus_action = max(action_votes, key=action_votes.get)
        
        # Consensus size (median)
        consensus_size = int(statistics.median(p.suggested_size for p in valid_predictions))
        
        # Agreement level
        if len(valid_predictions) >= 2:
            prob_std = statistics.stdev(p.probability for p in valid_predictions)
            agreement_level = max(0.0, 1.0 - (prob_std * 2))
        else:
            agreement_level = 1.0
        
        # Build reasoning
        reasoning_parts = []
        for p in valid_predictions:
            reasoning_parts.append(f"{p.llm_name} ({p.confidence:.0%}): {p.probability:.1%}")
        reasoning = " | ".join(reasoning_parts)
        
        return ConsensusDecision(
            ticker=ticker,
            consensus_prob=consensus_prob,
            consensus_action=consensus_action,
            consensus_size=consensus_size,
            agreement_level=agreement_level,
            predictions=valid_predictions,
            reasoning=reasoning
        )
    
    async def ask_claude_with_news(self, market_info: Dict, orderbook: Dict, news_articles: List) -> LLMPrediction:
        """Ask Claude for prediction."""
        if not self.claude:
            return LLMPrediction("Claude", 0.5, 0.0, "Not available", 0, "skip")
        
        try:
            prompt = self._build_prompt(market_info, orderbook, news_articles, "fundamentals")
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.claude.messages.create,
                    model=self.claude_model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                ),
                timeout=30.0
            )
            
            text = response.content[0].text
            return self._parse_prediction(text, "Claude")
        
        except Exception as e:
            log.error(f"Claude prediction failed: {e}")
            return LLMPrediction("Claude", 0.5, 0.0, f"Error: {e}", 0, "skip")
    
    async def ask_gpt_with_news(self, market_info: Dict, orderbook: Dict, news_articles: List) -> LLMPrediction:
        """Ask GPT-4 for prediction."""
        if not self.openai:
            return LLMPrediction("GPT-4", 0.5, 0.0, "Not available", 0, "skip")
        
        try:
            prompt = self._build_prompt(market_info, orderbook, news_articles, "technical")
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.openai.chat.completions.create,
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000
                ),
                timeout=30.0
            )
            
            text = response.choices[0].message.content
            return self._parse_prediction(text, "GPT-4")
        
        except Exception as e:
            log.error(f"GPT-4 prediction failed: {e}")
            return LLMPrediction("GPT-4", 0.5, 0.0, f"Error: {e}", 0, "skip")
    
    async def ask_gemini_with_news(self, market_info: Dict, orderbook: Dict, news_articles: List) -> LLMPrediction:
        """Ask Gemini for prediction."""
        if not self.gemini:
            return LLMPrediction("Gemini", 0.5, 0.0, "Not available", 0, "skip")
        
        try:
            prompt = self._build_prompt(market_info, orderbook, news_articles, "sentiment")
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.gemini.generate_content,
                    prompt
                ),
                timeout=30.0
            )
            
            text = response.text
            return self._parse_prediction(text, "Gemini")
        
        except Exception as e:
            log.error(f"Gemini prediction failed: {e}")
            return LLMPrediction("Gemini", 0.5, 0.0, f"Error: {e}", 0, "skip")
    
    def _build_prompt(self, market_info: Dict, orderbook: Dict, news_articles: List, focus: str) -> str:
        """Build prompt for LLM."""
        title = market_info.get('title', 'Unknown market')
        hours_to_close = market_info.get('hours_to_close', 999)
        
        best_yes_bid = orderbook.get('best_yes_bid', 0)
        best_yes_ask = orderbook.get('best_yes_ask', 100)
        market_prob = (best_yes_bid + best_yes_ask) / 200.0
        
        # Format news
        news_text = "No recent news"
        if news_articles:
            news_lines = []
            for i, article in enumerate(news_articles[:5], 1):
                news_lines.append(f"{i}. {article.title}")
            news_text = "\n".join(news_lines)
        
        prompt = f"""Predict outcome of this market:

MARKET: {title}
CLOSES IN: {hours_to_close:.1f} hours
CURRENT PROBABILITY: {market_prob:.1%}

RECENT NEWS:
{news_text}

FOCUS: {focus}

Respond with JSON:
{{
  "probability": 0.XX,
  "confidence": 0.XX,
  "reasoning": "brief explanation",
  "action": "buy_yes|buy_no|skip",
  "size": XX
}}
"""
        return prompt
    
    def _parse_prediction(self, text: str, llm_name: str) -> LLMPrediction:
        """Parse LLM response."""
        import json
        import re
        
        # Try to extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        try:
            # Try to find JSON object
            json_match = re.search(r'\{[^{}]*"probability"[^{}]*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            
            data = json.loads(text.strip())
            return LLMPrediction(
                llm_name=llm_name,
                probability=float(data.get('probability', 0.5)),
                confidence=float(data.get('confidence', 0.5)),
                reasoning=data.get('reasoning', ''),
                suggested_size=int(data.get('size', 0)),
                suggested_action=data.get('action', 'skip')
            )
        except Exception as e:
            log.error(f"Failed to parse {llm_name} response: {e}")
            return LLMPrediction(llm_name, 0.5, 0.0, "Parse error", 0, "skip")
