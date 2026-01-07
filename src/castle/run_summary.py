from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _infer_trade_pnl(trades: pd.DataFrame) -> Tuple[Optional[int], Optional[int], Optional[float], str]:
    """
    Try to infer per-trade win/loss from common columns.
    Returns: (wins, losses, pnl_usd, note)

    NOTE: This is only available if trades.csv contains per-trade P&L columns.
    Otherwise, win/loss proxy is unavailable.
    """
    if trades.empty:
        return 0, 0, 0.0, "No trades."

    if "pnl_usd" in trades.columns:
        pnl = pd.to_numeric(trades["pnl_usd"], errors="coerce").dropna()
        if len(pnl) == 0:
            return None, None, None, "pnl_usd present but empty/unparseable."
        wins = int((pnl > 0).sum())
        losses = int((pnl < 0).sum())
        return wins, losses, float(pnl.sum()), "Win/loss computed from trades.pnl_usd (proxy)."

    if "pnl_cents" in trades.columns:
        pnl = pd.to_numeric(trades["pnl_cents"], errors="coerce").dropna()
        if len(pnl) == 0:
            return None, None, None, "pnl_cents present but empty/unparseable."
        wins = int((pnl > 0).sum())
        losses = int((pnl < 0).sum())
        return wins, losses, float(pnl.sum()) / 100.0, "Win/loss computed from trades.pnl_cents (proxy)."

    return None, None, None, "Per-trade P&L columns not found; win/loss proxy unavailable."


def write_run_summary(run_dir: Path) -> None:
    summary = _read_json(run_dir / "summary.json")
    cfg = _read_json(run_dir / "config.redacted.json")

    equity = _read_csv_safe(run_dir / "equity.csv")
    trades = _read_csv_safe(run_dir / "trades.csv")
    decisions = _read_csv_safe(run_dir / "decisions.csv")

    eq_start = float(equity.iloc[0]["equity_usd"]) if (not equity.empty and "equity_usd" in equity.columns) else None
    eq_end = float(equity.iloc[-1]["equity_usd"]) if (not equity.empty and "equity_usd" in equity.columns) else None
    eq_delta = (eq_end - eq_start) if (eq_start is not None and eq_end is not None) else None

    trades_executed = int(summary.get("trades", len(trades) if not trades.empty else 0))
    decisions_n = int(summary.get("decisions", len(decisions) if not decisions.empty else 0))

    wins, losses, pnl_usd, pnl_note = _infer_trade_pnl(trades)

    out: Dict[str, Any] = {
        "run_id": summary.get("run_id", run_dir.name),
        "mode": summary.get("mode"),
        "decisions": decisions_n,
        "trades_executed": trades_executed,
        "equity_start_usd": eq_start,
        "equity_end_usd": eq_end,
        "equity_delta_usd": eq_delta,
        "win_loss_proxy": {
            "wins": wins,
            "losses": losses,
            "pnl_usd": pnl_usd,
            "note": pnl_note,
        },
        "notes": [],
    }

    maker_only = cfg.get("maker_only", None)
    if out["mode"] == "paper" and maker_only is True and trades_executed == 0:
        out["notes"].append(
            "Maker-only paper mode produced 0 trades. If you want end-to-end execution testing, "
            "temporarily enable non-maker/taker testing in paper mode and compare metrics."
        )

    (run_dir / "run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    def _sz(name: str) -> int:
        fp = run_dir / name
        return fp.stat().st_size if fp.exists() else -1

    txt = [
        f"Run: {out['run_id']}",
        f"Mode: {out.get('mode')}",
        f"Decisions: {out.get('decisions')}",
        f"Trades executed: {out.get('trades_executed')}",
    ]
    if eq_start is not None and eq_end is not None:
        txt.append(f"Equity start/end: {eq_start:.2f} -> {eq_end:.2f} (Δ {eq_delta:.2f})")

    wl = out["win_loss_proxy"]
    txt.append(
        f"Win/Loss proxy: {wl.get('wins')}/{wl.get('losses')}  P&L: {wl.get('pnl_usd')}  ({wl.get('note')})"
    )

    txt.append("Artifacts:")
    txt.append(f"  logs.txt bytes: {_sz('logs.txt')}")
    txt.append(f"  decisions.csv bytes: {_sz('decisions.csv')}")
    txt.append(f"  trades.csv bytes: {_sz('trades.csv')}")
    txt.append(f"  equity.csv bytes: {_sz('equity.csv')}")

    for n in out["notes"]:
        txt.append(f"Note: {n}")

    (run_dir / "run_summary.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
