from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)

def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

def redact_config(cfg: dict) -> dict:
    out = dict(cfg)
    # don't leak secrets
    for k in list(out.keys()):
        if "KEY" in k or "PRIVATE" in k or "TOKEN" in k:
            out[k] = "***REDACTED***" if out[k] else out[k]
    return out
