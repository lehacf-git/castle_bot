from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

@dataclass
class GeminiClient:
    api_key: str
    model: str = "gemini-1.5-flash"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    def generate_text(self, *, prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
        """Call Gemini generateContent via API key auth.

        Uses the Google AI for Developers Gemini API (Generative Language API).
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set")

        url = f"{self.base_url}/models/{self.model}:generateContent"
        params = {"key": self.api_key}

        contents = []
        if system:
            # Gemini supports system instructions via a special role in newer APIs,
            # but compatibility varies. We embed system guidance into the first user message
            # to keep it robust.
            prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER:\n{prompt}"

        contents.append({
            "role": "user",
            "parts": [{"text": prompt}],
        })

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": float(temperature),
            },
        }

        r = requests.post(url, params=params, json=payload, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini error {r.status_code}: {r.text}")

        data = r.json()
        # Typical response: candidates[0].content.parts[0].text
        cands = data.get("candidates") or []
        if not cands:
            return ""
        content = (cands[0].get("content") or {})
        parts = content.get("parts") or []
        texts = []
        for p in parts:
            t = p.get("text")
            if t:
                texts.append(t)
        return "\n".join(texts).strip()
