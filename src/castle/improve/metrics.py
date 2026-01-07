from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any
import json

import pandas as pd


@dataclass(frozen=True)
class RunMetrics:
    run_id: str
    mode: str
    trades: int
    decisions: int
    duration_minutes: float
    final_equity_usd: float | None
    max_drawdown_usd: float | None
    turnover_usd: float | None
    notes: str


def compute_metrics(run_dir: Path) -> RunMetrics:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary.json in {run_dir}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run_id = summary.get("run_id", run_dir.name)
    mode = summary.get("mode", "unknown")
    trades = int(summary.get("trades", 0))
    decisions = int(summary.get("decisions", 0))
    duration_minutes = float(summary.get("minutes", 0))

    equity_path = run_dir / "equity.csv"
    trades_path = run_dir / "trades.csv"

    final_equity = None
    max_dd = None
    turnover = None
    notes = ""

    # Equity
    if equity_path.exists():
        try:
            eq = pd.read_csv(equity_path)
        except pd.errors.EmptyDataError:
            eq = pd.DataFrame()
        if not eq.empty:
            if "equity_usd" in eq.columns:
                final_equity = float(eq["equity_usd"].iloc[-1])
                peak = eq["equity_usd"].cummax()
                dd = eq["equity_usd"] - peak
                max_dd = float(dd.min())
            elif "mtm_value_usd" in eq.columns:
                final_equity = float(eq["mtm_value_usd"].iloc[-1])

    # Trades / turnover
    if trades_path.exists():
        try:
            # If file exists but is empty, pandas throws EmptyDataError
            if trades_path.stat().st_size == 0:
                tr = pd.DataFrame()
            else:
                tr = pd.read_csv(trades_path)
        except pd.errors.EmptyDataError:
            tr = pd.DataFrame()

        if not tr.empty and "price_cents" in tr.columns and "count" in tr.columns:
            turnover = float(((tr["price_cents"] / 100.0) * tr["count"]).sum())

    if trades == 0:
        notes = (
            "No trades executed. In paper mode, maker-only behavior may lead to no fills. "
            "Try increasing minutes, lowering MIN_EDGE_PROB, or temporarily set MAKER_ONLY=false to test taker logic."
        )

    return RunMetrics(
        run_id=run_id,
        mode=mode,
        trades=trades,
        decisions=decisions,
        duration_minutes=duration_minutes,
        final_equity_usd=final_equity,
        max_drawdown_usd=max_dd,
        turnover_usd=turnover,
        notes=notes,
    )


def metrics_to_dict(m: RunMetrics) -> Dict[str, Any]:
    return {
        "run_id": m.run_id,
        "mode": m.mode,
        "trades": m.trades,
        "decisions": m.decisions,
        "duration_minutes": m.duration_minutes,
        "final_equity_usd": m.final_equity_usd,
        "max_drawdown_usd": m.max_drawdown_usd,
        "turnover_usd": m.turnover_usd,
        "notes": m.notes,
    }
