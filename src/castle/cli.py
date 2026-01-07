# PATCH for src/castle/cli.py
# Add mode validation and training mode support

# In the run() command, replace the mode validation section with:

@app.command()
def run(
    minutes: int = typer.Option(5, help="How long to run the loop."),
    mode: str = typer.Option(None, help="test|paper|training|demo|prod (overrides env CASTLE_MODE)."),
    limit_markets: int = typer.Option(40, help="How many open markets to scan each cycle."),
):
    """Run the bot.
    
    Modes:
    - test: Demo env, API validation only
    - paper: Simulate fills (default)
    - training: Prod data, no trading, "would trade" logs
    - demo: Place orders in demo env
    - prod: Place orders in prod env (REQUIRES EXPLICIT CONFIRMATION)
    """
    s = get_settings()
    setup_logging(s.log_level)
    engine = make_engine(s.db_url)
    init_db(engine)

    m = (mode or s.mode).lower().strip()
    valid_modes = {"test", "paper", "training", "demo", "prod"}
    if m not in valid_modes:
        raise typer.BadParameter(f"mode must be one of: {', '.join(valid_modes)}")
    
    # Safety checks
    if m == "prod":
        console.print("[bold red]WARNING: PROD mode will place REAL orders with REAL money![/bold red]")
        console.print(f"Environment: {s.kalshi_env}")
        console.print(f"Bankroll: ${s.bankroll_usd}")
        confirm = typer.confirm("Are you absolutely sure you want to trade in PROD mode?")
        if not confirm:
            raise typer.Abort("Cancelled by user")
    
    if m == "training":
        if s.kalshi_env != "prod":
            console.print("[yellow]Note: Training mode works best with KALSHI_ENV=prod[/yellow]")
        console.print("[cyan]Training mode: Will use real market data but NOT place orders[/cyan]")

    run_dir = run_loop(engine=engine, settings=s, minutes=minutes, mode=m, limit_markets=limit_markets)
    console.print(f"[green]Run complete[/green]: {run_dir}")
    
    # Show quick diagnostics
    import json
    diag_path = run_dir / "diagnostics.json"
    if diag_path.exists():
        diag = json.loads(diag_path.read_text())
        console.print("\n[bold]Quick Diagnostics:[/bold]")
        console.print(f"  Markets seen: {diag.get('markets_seen', 0)}")
        console.print(f"  With orderbooks: {diag.get('markets_with_orderbooks', 0)}")
        console.print(f"  Decisions generated: {diag.get('decisions_generated', 0)}")
        console.print(f"  Trades filled: {diag.get('trades_filled', 0)}")
        
        skip_reasons = diag.get('skip_reasons', {})
        if skip_reasons:
            console.print("\n[bold]Top skip reasons:[/bold]")
            sorted_skips = sorted(skip_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
            for reason, count in sorted_skips:
                console.print(f"  {reason}: {count}")
