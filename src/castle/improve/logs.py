from __future__ import annotations

from pathlib import Path
import re

# Conservative redaction patterns (avoid leaking secrets). This will over-redact on purpose.
_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),  # Google-style API keys
    re.compile(r"sk-[0-9A-Za-z\-_]{20,}"),   # common key prefix
    re.compile(r"(?i)kalshi-access-(key|signature|timestamp)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret|token|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"),
]

def redact_text(text: str) -> str:
    out = text
    for pat in _PATTERNS:
        out = pat.sub("***REDACTED***", out)
    return out

def tail_redacted(path: Path, *, max_lines: int = 800) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    tail = "\n".join(lines[-max_lines:])
    return redact_text(tail)
