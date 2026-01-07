from __future__ import annotations

from pathlib import Path
import pandas as pd

def summarize_csv(path: Path, *, max_rows: int = 50) -> str:
    if not path.exists():
        return ""
    try:
        df = pd.read_csv(path)
    except Exception:
        return ""
    if df.empty:
        return ""
    # Keep last N rows
    df2 = df.tail(max_rows)
    return df2.to_csv(index=False)
