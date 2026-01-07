from __future__ import annotations

import json
import logging
import os
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
    mode: str = typer.Option(None, help="paper|demo|prod (overrides env CASTLE_MODE)."),
    limit_markets: int = typer.Option(40, help="How many open markets to scan each cycle."),
    min_volume: int = typer.Option(0, help="Minimum 24h volume filter."),
    min_open_interest: int = typer.Option(50, help="Minimum open interest filter."),
):
    """Run the bot."""
    s = get_settings()
    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)

    m = (mode or s.mode).lower().strip()
    if m not in {"paper", "demo", "prod"}:
        raise typer.BadParameter("mode must be paper|demo|prod")

    run_dir = run_loop(
        engine=engine,
        settings=s,
        minutes=minutes,
        mode=m,
        limit_markets=limit_markets,
        min_volume_24h=min_volume,
        min_open_interest=min_open_interest
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
        if "estimated_trades_if_taker_enabled" in diag:
            table.add_row("Est. trades if taker enabled", str(diag["estimated_trades_if_taker_enabled"]))

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
    """Ask the codegen model (Gemini) to propose file edits based on requirements + run metrics."""
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
    limit_markets: int = typer.Option(40, "--limit-markets", help="How many markets to scan each loop."),
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


# Resource management commands
resources_app = typer.Typer(help="Manage resource requests from autonomous improvement")
app.add_typer(resources_app, name="resources")


@resources_app.command("list")
def resources_list(
    priority: str = typer.Option(None, help="Filter by priority: critical|high|medium|low"),
    status: str = typer.Option("pending", help="Filter by status: pending|approved|implemented|rejected")
):
    """List resource requests."""
    from .improve.resource_requests import ResourceRequestManager, Priority
    
    repo_root = Path(__file__).resolve().parents[2]
    manager = ResourceRequestManager(repo_root / "resource_requests.json")
    
    requests = manager.requests
    
    # Filter by status
    if status:
        requests = [r for r in requests if r.status == status]
    
    # Filter by priority
    if priority:
        priority_enum = Priority(priority.lower())
        requests = [r for r in requests if r.priority == priority_enum]
    
    if not requests:
        console.print("[yellow]No matching requests found[/yellow]")
        return
    
    # Display table
    table = Table(title=f"Resource Requests ({status})")
    table.add_column("ID")
    table.add_column("Priority")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Expected Impact")
    
    for req in requests:
        table.add_row(
            req.request_id[-12:],
            req.priority.value.upper(),
            req.resource_type.value,
            req.title[:40],
            req.expected_improvement[:50]
        )
    
    console.print(table)


@resources_app.command("view")
def resources_view(request_id: str = typer.Argument(..., help="Request ID to view")):
    """View detailed information about a resource request."""
    from .improve.resource_requests import ResourceRequestManager
    
    repo_root = Path(__file__).resolve().parents[2]
    manager = ResourceRequestManager(repo_root / "resource_requests.json")
    
    req = None
    for r in manager.requests:
        if r.request_id == request_id or r.request_id.endswith(request_id):
            req = r
            break
    
    if not req:
        console.print(f"[red]Request {request_id} not found[/red]")
        raise typer.Exit(1)
    
    # Display detailed info
    console.print(f"\n[bold]Resource Request: {req.title}[/bold]")
    console.print(f"ID: {req.request_id}")
    console.print(f"Priority: {req.priority.value.upper()}")
    console.print(f"Type: {req.resource_type.value}")
    console.print(f"Status: {req.status}")
    console.print(f"Requested: {req.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n")
    
    console.print("[bold]Description:[/bold]")
    console.print(req.description + "\n")
    
    console.print("[bold]Justification:[/bold]")
    console.print(req.justification + "\n")
    
    console.print("[bold]Expected Improvement:[/bold]")
    console.print(req.expected_improvement + "\n")
    
    console.print("[bold]Cost Estimate:[/bold]")
    console.print(req.cost_estimate + "\n")
    
    if req.alternatives:
        console.print("[bold]Alternatives:[/bold]")
        for alt in req.alternatives:
            console.print(f"  • {alt}")
        console.print()


@resources_app.command("approve")
def resources_approve(
    request_id: str = typer.Argument(..., help="Request ID to approve"),
    notes: str = typer.Option("", help="Optional approval notes")
):
    """Approve a resource request."""
    from .improve.resource_requests import ResourceRequestManager
    
    repo_root = Path(__file__).resolve().parents[2]
    manager = ResourceRequestManager(repo_root / "resource_requests.json")
    
    # Support partial IDs
    full_id = None
    for r in manager.requests:
        if r.request_id == request_id or r.request_id.endswith(request_id):
            full_id = r.request_id
            break
    
    if not full_id:
        console.print(f"[red]Request {request_id} not found[/red]")
        raise typer.Exit(1)
    
    manager.approve_request(full_id, operator_notes=notes)
    console.print(f"[green]✓[/green] Request {full_id} approved")


@resources_app.command("reject")
def resources_reject(
    request_id: str = typer.Argument(..., help="Request ID to reject"),
    reason: str = typer.Option(..., "--reason", help="Reason for rejection")
):
    """Reject a resource request."""
    from .improve.resource_requests import ResourceRequestManager
    
    repo_root = Path(__file__).resolve().parents[2]
    manager = ResourceRequestManager(repo_root / "resource_requests.json")
    
    # Support partial IDs
    full_id = None
    for r in manager.requests:
        if r.request_id == request_id or r.request_id.endswith(request_id):
            full_id = r.request_id
            break
    
    if not full_id:
        console.print(f"[red]Request {request_id} not found[/red]")
        raise typer.Exit(1)
    
    manager.reject_request(full_id, reason=reason)
    console.print(f"[red]✗[/red] Request {full_id} rejected")


@resources_app.command("export")
def resources_export(
    output: str = typer.Option("RESOURCE_REQUESTS.md", help="Output file path")
):
    """Export pending requests for operator review."""
    from .improve.resource_requests import ResourceRequestManager
    
    repo_root = Path(__file__).resolve().parents[2]
    manager = ResourceRequestManager(repo_root / "resource_requests.json")
    
    output_path = Path(output)
    manager.export_for_operator(output_path)
    
    console.print(f"[green]✓[/green] Exported to {output_path}")
    console.print(f"Pending requests: {len(manager.get_pending_requests())}")


@app.command()
def trade_autonomous(
    mode: str = typer.Option("training", help="training|demo|prod"),
    minutes: int = typer.Option(60, help="Minutes per cycle"),
    cycles: int = typer.Option(10, help="Number of improve cycles"),
    anthropic_key: str = typer.Option(None, "--anthropic-key", help="Anthropic API key"),
    openai_key: str = typer.Option(None, "--openai-key", help="OpenAI API key"),
    gemini_key: str = typer.Option(None, "--gemini-key", help="Gemini API key"),
):
    """
    FULLY AUTONOMOUS MULTI-LLM TRADING SYSTEM
    
    - Prioritizes hourly/daily markets
    - Consults 3 LLMs for each decision
    - Takes profits quickly (10-20% targets)
    - Claude generates code improvements
    - Learns from every trade
    """
    console.print("[red]ERROR: Autonomous trading system not yet implemented[/red]")
    console.print("This command requires additional modules:")
    console.print("  - src/castle/strategy/multi_llm_advisor.py")
    console.print("  - src/castle/strategy/autonomous_trader.py")
    console.print("  - src/castle/news/news_aggregator.py")
    console.print("  - src/castle/improve/resource_requests.py")
    console.print("\nPlease implement these modules first.")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
