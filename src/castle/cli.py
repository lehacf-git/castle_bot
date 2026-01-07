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

# Valid modes
VALID_MODES = {"test", "paper", "training", "demo", "prod"}

def _validate_mode(mode: str) -> str:
    """Validate and return normalized mode."""
    m = mode.lower().strip()
    if m not in VALID_MODES:
        raise typer.BadParameter(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
    return m

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
    Run the bot in one of these modes:
    
    - test: Demo environment API validation, no trading
    - paper: Simulate fills locally, no real trading
    - training: Production market data, no trading (for research)
    - demo: Place real orders in Kalshi demo environment
    - prod: Place real orders in Kalshi production environment
    """
    s = get_settings()
    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)

    m = _validate_mode(mode or s.mode)
    
    # Safety check: prod/demo require explicit confirmation
    if m in {"prod", "demo"}:
        console.print(f"[yellow bold]WARNING: You are about to run in {m.upper()} mode![/yellow bold]")
        console.print(f"This will place REAL orders in the Kalshi {m} environment.")
        confirm = typer.confirm("Are you sure you want to continue?")
        if not confirm:
            raise typer.Abort()

    run_dir = run_loop(
        engine=engine,
        settings=s,
        minutes=minutes,
        mode=m,
        limit_markets=limit_markets
    )
    console.print(f"[green]Run complete[/green]: {run_dir}")

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
    run_summary = json.loads((runs_dir / "run_summary.json").read_text(encoding="utf-8")) if (runs_dir / "run_summary.json").exists() else {}

    table = Table(title=f"Run {run_id}")
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("Mode", str(summary.get("mode")))
    table.add_row("Env", str(summary.get("env", "unknown")))
    table.add_row("Trades", str(summary.get("trades")))
    table.add_row("Decisions", str(summary.get("decisions")))

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
        
        diag = run_summary.get("diagnostics") or {}
        if diag:
            table.add_row("Markets scanned", str(diag.get("markets_scanned", 0)))
            table.add_row("Markets with books", str(diag.get("markets_with_orderbooks", 0)))
            table.add_row("Skip reasons (top 3)", str(diag.get("top_skip_reasons", [])))

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
    """Ask the codegen model to propose file edits based on requirements + run metrics."""
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
    minutes: int = typer.Option(10, "--minutes", help="Minutes to run the bot in this cycle."),
    limit_markets: int = typer.Option(100, "--limit-markets", help="How many markets to scan each loop."),
    mode: str = typer.Option("paper", "--mode", help="Mode to run in (paper/training recommended for automation)."),
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

    m = _validate_mode(mode)

    # Run
    from .runner import run_loop
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
