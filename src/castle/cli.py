from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .logging import setup_logging
from .db import make_engine
from .runner import init_db, run_loop
from .reporting import write_json

app = typer.Typer(add_completion=False)
console = Console()

@app.command()
def init_db_cmd():
    """Create DB tables."""
    s = get_settings()
    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)
    console.print(f"[green]DB initialized[/green] at {s.db_url}")

@app.command()
def run(
    minutes: int = typer.Option(5, help="How long to run the loop."),
    mode: str = typer.Option(None, help="test|paper|training|demo|prod (overrides env CASTLE_MODE)."),
    limit_markets: int = typer.Option(100, help="How many open markets to scan each cycle."),
):
    """
    Run the bot in different modes:
    
    \b
    - test: demo env, validate API (no trading)
    - paper: simulate fills (no trading) 
    - training: prod data without trading (logs "would trade")
    - demo: place orders in Kalshi demo env
    - prod: place orders in Kalshi production env
    """
    s = get_settings()
    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)

    # Override mode if specified
    m = (mode or s.mode).lower().strip()
    
    # Validate mode
    valid_modes = {"test", "paper", "training", "demo", "prod"}
    if m not in valid_modes:
        console.print(f"[red]Error:[/red] Invalid mode '{m}'. Must be one of: {', '.join(valid_modes)}")
        raise typer.Exit(code=1)
    
    # Safety checks
    if m in {"demo", "prod"}:
        if not s.kalshi_key_id or not s.kalshi_private_key_path:
            console.print(f"[red]Error:[/red] Mode '{m}' requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
            raise typer.Exit(code=1)
    
    if m == "training":
        if s.kalshi_env != "prod":
            console.print("[red]Error:[/red] Training mode requires KALSHI_ENV=prod (uses prod data without trading)")
            raise typer.Exit(code=1)
        console.print("[yellow]Warning:[/yellow] Training mode uses PRODUCTION data without placing orders")
    
    if m == "test":
        if s.kalshi_env != "demo":
            console.print("[red]Error:[/red] Test mode requires KALSHI_ENV=demo (validates API in demo environment)")
            raise typer.Exit(code=1)
    
    if m in {"demo", "prod"}:
        console.print(f"[yellow]⚠️  LIVE TRADING MODE: {m.upper()} ⚠️[/yellow]")
        console.print("Orders will be placed in the Kalshi environment.")
        if not typer.confirm("Continue?", default=False):
            raise typer.Exit(code=0)

    console.print(f"[cyan]Starting run:[/cyan] mode={m}, kalshi_env={s.kalshi_env}, minutes={minutes}")
    
    run_dir = run_loop(engine=engine, settings=s, minutes=minutes, mode=m, limit_markets=limit_markets)
    console.print(f"[green]Run complete[/green]: {run_dir}")
    console.print(f"Review: [cyan]castle report {run_dir.name}[/cyan]")

@app.command()
def report(run_id: str = typer.Argument(..., help="Run id folder name under runs/")):
    """Print a quick report for a run."""
    s = get_settings()
    runs_dir = s.runs_dir / run_id
    if not runs_dir.exists():
        raise typer.BadParameter(f"Run not found: {runs_dir}")

    import pandas as pd
    from pandas.errors import EmptyDataError

    def _read_csv_safe(p):
        try:
            if not p.exists() or p.stat().st_size == 0:
                return pd.DataFrame()
            return pd.read_csv(p)
        except EmptyDataError:
            return pd.DataFrame()

    summary = json.loads((runs_dir / "summary.json").read_text(encoding="utf-8"))
    trades = _read_csv_safe(runs_dir / "trades.csv")
    equity = _read_csv_safe(runs_dir / "equity.csv")
    decisions = _read_csv_safe(runs_dir / "decisions.csv")
    would_trade = _read_csv_safe(runs_dir / "would_trade.csv")
    run_summary = json.loads((runs_dir / "run_summary.json").read_text(encoding="utf-8")) if (runs_dir / "run_summary.json").exists() else {}

    table = Table(title=f"Run {run_id}")
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("Mode", str(summary.get("mode")))
    table.add_row("Kalshi Env", str(summary.get("kalshi_env", "unknown")))
    table.add_row("Cycles", str(summary.get("cycles", "?")))
    table.add_row("Decisions", str(len(decisions)))
    table.add_row("Trades", str(len(trades)))
    
    if not would_trade.empty:
        table.add_row("Would-Trade Entries", str(len(would_trade)))

    # Diagnostics
    diag = summary.get("diagnostics", {})
    if diag:
        table.add_row("─" * 20, "─" * 20)
        table.add_row("Markets Fetched", str(diag.get("markets_fetched", 0)))
        table.add_row("Markets w/ Orderbooks", str(diag.get("markets_with_orderbooks", 0)))
        table.add_row("Empty Orderbooks", str(diag.get("markets_empty_orderbook", 0)))
        table.add_row("Spread Too Wide", str(diag.get("markets_spread_too_wide", 0)))
        table.add_row("Insufficient Depth", str(diag.get("markets_insufficient_depth", 0)))
        table.add_row("Insufficient Edge", str(diag.get("markets_insufficient_edge", 0)))

    if run_summary:
        mtm = run_summary.get("mtm_proxy") or {}
        wins = mtm.get("wins")
        losses = mtm.get("losses")
        flats = mtm.get("flats")
        pnl_usd = mtm.get("pnl_usd")
        if wins is not None and losses is not None:
            table.add_row("MTM wins/losses/flats", f"{wins}/{losses}/{flats}")
        if pnl_usd is not None:
            table.add_row("MTM P&L (usd)", str(pnl_usd))

    if not equity.empty:
        table.add_row("Last exposure_usd", str(equity.iloc[-1].get("exposure_usd")))
        table.add_row("Last mtm_value_usd", str(equity.iloc[-1].get("mtm_value_usd")))
    
    console.print(table)


@app.command()
def bundle(run_id: str = typer.Argument(..., help="Run id to bundle into a zip")):
    """Create a zip bundle of run artifacts to share back for analysis."""
    s = get_settings()
    run_dir = s.runs_dir / run_id
    if not run_dir.exists():
        raise typer.BadParameter(f"Run not found: {run_dir}")
    zip_path = run_dir.with_suffix(".zip")

    import zipfile
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in run_dir.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(run_dir.parent)))
    console.print(f"[green]Bundle created[/green]: {zip_path}")


@app.command()
def eval(run_id: str = typer.Argument(..., help="Run id folder name under runs/")):
    """Compute evaluation metrics for a run."""
    s = get_settings()
    run_dir = s.runs_dir / run_id
    if not run_dir.exists():
        raise typer.BadParameter(f"Run not found: {run_dir}")
    from .improve.metrics import compute_metrics, metrics_to_dict
    m = compute_metrics(run_dir)
    console.print_json(json.dumps(metrics_to_dict(m), indent=2))

improve_app = typer.Typer(help="Spec-driven improvement workflow (propose/apply).")
app.add_typer(improve_app, name="improve")

@improve_app.command("propose")
def improve_propose(run_id: str = typer.Option(..., "--run-id", help="Run id to base the proposal on")):
    """Ask the codegen model (Gemini/OpenAI) to propose file edits based on requirements + run metrics."""
    s = get_settings()
    provider = (s.codegen_provider or "openai").lower().strip()
    if provider == "openai" and not s.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is not set in your environment/.env")
    if provider == "gemini" and not s.gemini_api_key:
        raise typer.BadParameter("GEMINI_API_KEY is not set in your environment/.env")
    from .improve.proposer import propose
    repo_root = Path(__file__).resolve().parents[2]  # repo root when installed editable
    res = propose(s, repo_root=repo_root, run_id=run_id)
    console.print(f"[green]Proposal created[/green]: {res.proposal_id} at {res.proposal_dir}")

@improve_app.command("apply")
def improve_apply(
    proposal_id: str = typer.Option(..., "--proposal-id", help="Proposal id under proposals/"),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip compileall preflight"),
):
    """Apply a proposal bundle (copies proposed files into the repo) and runs a compile check."""
    from .improve.applier import apply_proposal
    repo_root = Path(__file__).resolve().parents[2]
    res = apply_proposal(repo_root=repo_root, proposal_id=proposal_id, run_tests=not no_tests)
    if not res.ok:
        raise typer.Exit(code=1)
    console.print(f"[green]{res.message}[/green] Applied files: {len(res.applied_files)}")

@improve_app.command("cycle")
def improve_cycle(
    minutes: int = typer.Option(10, "--minutes", help="Minutes to run the bot in this cycle (paper/demo/prod per config)."),
    limit_markets: int = typer.Option(100, "--limit-markets", help="How many markets to scan each loop."),
):
    """Run -> eval -> propose (does NOT auto-apply)."""
    s = get_settings()
    provider = (s.codegen_provider or "openai").lower().strip()
    if provider == "openai" and not s.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is not set in your environment/.env")
    if provider == "gemini" and not s.gemini_api_key:
        raise typer.BadParameter("GEMINI_API_KEY is not set in your environment/.env")

    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)

    # Run
    from .runner import run_loop
    m = (s.mode or "paper").lower().strip()
    run_dir = run_loop(engine=engine, settings=s, minutes=minutes, mode=m, limit_markets=limit_markets)
    run_id = run_dir.name

    # Eval
    from .improve.metrics import compute_metrics, metrics_to_dict
    metrics = metrics_to_dict(compute_metrics(run_dir))
    console.print_json(json.dumps(metrics, indent=2))

    # Propose
    from .improve.proposer import propose
    repo_root = Path(__file__).resolve().parents[2]
    res = propose(s, repo_root=repo_root, run_id=run_id)
    console.print(f"[green]Proposal created[/green]: {res.proposal_id} at {res.proposal_dir}")

if __name__ == "__main__":
    app()
