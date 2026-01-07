from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

@dataclass
class OpenAIResponsesClient:
    api_key: str
    model: str = "gpt-5.2"
    base_url: str = "https://api.openai.com/v1"

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_response(self, *, input_items: Any, instructions: Optional[str] = None, text_format: Optional[Dict[str, Any]] = None, temperature: float = 0.2) -> Dict[str, Any]:
        url = f"{self.base_url}/responses"
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": input_items,
            "temperature": float(temperature),
            "store": False,
        }
        if instructions:
            payload["instructions"] = instructions
        if text_format:
            payload["text"] = {"format": text_format}

        r = requests.post(url, headers=self._headers(), json=payload, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI Responses error {r.status_code}: {r.text}")
        return r.json()

    @staticmethod
    def extract_output_text(resp: Dict[str, Any]) -> str:
        # The Responses API returns an "output" list with message items. We aggregate all output_text parts.
        out = resp.get("output") or []
        chunks = []
        for item in out:
            if item.get("type") != "message":
                continue
            if item.get("role") != "assistant":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        return "\n".join(chunks).strip()

    def generate_json(self, *, system: str, user: str, schema: Dict[str, Any], schema_name: str = "proposal", temperature: float = 0.2) -> Dict[str, Any]:
        # Structured Outputs via text.format with type=json_schema, strict=true. See docs.
        text_format = {
            "type": "json_schema",
            "strict": True,
            "name": schema_name,
            "schema": schema,
        }
        input_items = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self.create_response(input_items=input_items, text_format=text_format, temperature=temperature)
        text = self.extract_output_text(resp)
        if not text:
            raise RuntimeError("OpenAI returned empty output_text")
        return json.loads(text)
