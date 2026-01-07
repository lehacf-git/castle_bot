# The Castle (MVP) — Kalshi Paper/Demo Trading Research Bot

This repository is an **MVP research scaffold** for:
- Ingesting Kalshi market data (public endpoints)
- Optionally ingesting news (RSS)
- Generating simple features + signals
- Executing in **paper mode** (default) or **Kalshi demo** (optional)
- Producing run artifacts you can share back for analysis & iterative improvement

> ⚠️ Not financial advice. Use the **demo environment first** and comply with Kalshi rules and your local laws.

## Quick start

### 1) Create a venv and install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### 2) Configure environment
Copy `.env.example` to `.env` and edit.

```bash
cp .env.example .env
```

### 3) Initialize DB
```bash
castle init-db-cmd
```

### 4) Run (paper mode, default)
```bash
castle run --minutes 5
```

### 5) (Optional) Run against Kalshi **demo** execution
You need a demo account + API key id + private key file.
```bash
castle run --minutes 5 --mode demo
```

Kalshi demo API root: `https://demo-api.kalshi.co/trade-api/v2` (public docs).

## What you share back for the feedback loop

After a run, you will have:
- `runs/<run_id>/summary.json`
- `runs/<run_id>/trades.csv`
- `runs/<run_id>/equity.csv`
- `runs/<run_id>/config.redacted.json`
- `runs/<run_id>/logs.txt`

Bundle them:
```bash
castle bundle --run-id <run_id>
```

Then upload the generated zip back into this chat. I can analyze the metrics and propose code changes.

## Commands
- `castle init-db-cmd`
- `castle run --minutes N [--mode paper|demo|prod]`
- `castle report --run-id <run_id>`
- `castle bundle --run-id <run_id>`

## Repo layout
- `src/castle/kalshi/` : Kalshi REST client + auth
- `src/castle/news/`   : RSS ingestion
- `src/castle/strategy/`: feature extraction + signal + sizing
- `src/castle/execution/`: paper + kalshi execution
- `src/castle/cli.py`  : command line entrypoint


## Security note (important)
- Do **NOT** put API keys into the repository or commit history.
- Keep secrets in `.env` (ignored by git) or a local `secrets/` folder.
- If you accidentally pasted keys into chat or a public place, rotate them immediately.

## Self-improvement loop (spec-driven, gated)

The repo includes a **requirements spec** at `minions/requirements.yaml` and a **proposal system**
that can ask a codegen model (Gemini) to propose file-level edits based on run metrics.

**Workflow**
1. Run a paper/demo session:
   ```bash
   castle run --minutes 10
   ```
2. Evaluate the run:
   ```bash
   castle eval --run-id <RUN_ID>
   ```
3. Propose improvements (writes to `proposals/<proposal_id>/`):
   ```bash
   castle improve propose --run-id <RUN_ID>
   ```
4. Review proposed files in `proposals/<proposal_id>/files/`
5. Apply (runs `python -m compileall src`):
   ```bash
   castle improve apply --proposal-id <proposal_id>
   ```

**Safety**
- Proposals are never applied automatically.
- Keep `CASTLE_MODE=paper` for automation. Only switch to demo/prod intentionally.

### About sending logs to Gemini
`castle improve propose` includes:
- redacted tail of `runs/<run_id>/logs.txt`
- tail snapshots of decisions/trades/equity CSVs

The redaction is intentionally conservative, but you should still avoid logging secrets.

## Using OpenAI for analytics/codegen

Set in `.env`:

- `CODEGEN_PROVIDER=openai`
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-5.2` (default)

The codegen system uses the **Responses API** and **Structured Outputs** (`text.format` with JSON Schema)
to produce machine-applyable proposals. See OpenAI docs for authentication and Responses usage.
