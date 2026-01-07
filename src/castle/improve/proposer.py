from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import Settings
from ..llm.gemini import GeminiClient
from ..llm.openai_responses import OpenAIResponsesClient
from .logs import tail_redacted
from .metrics import compute_metrics, metrics_to_dict
from .requirements import load_requirements
from .snapshot import summarize_csv

SYSTEM = """You are a codegen assistant for the 'castle' repo.

CRITICAL repo layout rules:
- The Python package is 'castle' under src/castle/.
- Do NOT create a new top-level package (e.g., castle_bot/). Never propose paths outside this repo's layout.
- All file edits MUST be within one of these allowed prefixes:
  - src/castle/
  - tests/
  - minions/requirements.yaml
  - README.md
  - .env.example
  - .gitignore

Behavior rules:
- Never include or request secrets/keys.
- Prefer minimal, testable changes.
- If you change behavior, add/update a small unit test when feasible.

Return STRICT JSON that matches the provided JSON schema.
"""

PROPOSAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "rationale": {"type": "array", "items": {"type": "string"}},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "required": ["summary", "rationale", "changes"],
}

ALLOWED_PREFIXES: Tuple[str, ...] = (
    "src/castle/",
    "tests/",
    "minions/requirements.yaml",
    "README.md",
    ".env.example",
    ".gitignore",
)


@dataclass(frozen=True)
class ProposalResult:
    proposal_id: str
    proposal_dir: Path


def _repo_manifest(repo_root: Path) -> str:
    """Return a newline-separated list of relevant repo files to anchor the model."""
    paths: List[str] = []
    for base in [repo_root / "src" / "castle", repo_root / "tests", repo_root / "minions"]:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".yaml", ".yml", ".md"}:
                paths.append(str(p.relative_to(repo_root)).replace("\\", "/"))
    return "\n".join(sorted(set(paths)))


def _validate_proposal_paths(data: Dict[str, Any]) -> None:
    changes = data.get("changes") or []
    bad: List[str] = []
    for ch in changes:
        p = str(ch.get("path", "")).lstrip("/").replace("\\", "/")
        if ".." in p.split("/"):
            bad.append(p)
            continue
        if not p.startswith(ALLOWED_PREFIXES):
            bad.append(p)
    if bad:
        raise ValueError(
            "Proposal contains disallowed paths:\n"
            + "\n".join(f" - {p}" for p in bad)
            + "\nAllowed prefixes: " + ", ".join(ALLOWED_PREFIXES)
        )


def _build_prompt(
    *,
    requirements_yaml: str,
    metrics_json: str,
    logs_txt: str,
    decisions_csv: str,
    trades_csv: str,
    equity_csv: str,
    manifest_txt: str,
) -> str:
    return f"""REPO_MANIFEST (authoritative file list):
{manifest_txt}

REQUIREMENTS_YAML:
{requirements_yaml}

RUN_METRICS_JSON:
{metrics_json}

EQUITY_CSV_TAIL:
{equity_csv}

TRADES_CSV_TAIL:
{trades_csv}

DECISIONS_CSV_TAIL:
{decisions_csv}

LOGS_TAIL_REDACTED:
{logs_txt}

Task:
Propose minimal, testable improvements to strategy + evaluation that:
- Increase observability (skip reasons, coverage metrics)
- Avoid churn (dedup/cooldown)
- Make paper runs produce measurable activity WITHOUT optimistic assumptions

Constraints:
- All edits must target the existing 'castle' package under src/castle/.
- Do NOT create a new package or folder outside allowed prefixes.
- Output STRICT JSON matching the schema exactly.
"""


def propose(settings: Settings, *, repo_root: Path, run_id: str) -> ProposalResult:
    req_path = repo_root / "minions" / "requirements.yaml"
    load_requirements(req_path)
    requirements_yaml = req_path.read_text(encoding="utf-8")

    run_dir = settings.runs_dir / run_id
    m = compute_metrics(run_dir)
    metrics_json = json.dumps(metrics_to_dict(m), indent=2)

    logs_txt = tail_redacted(run_dir / "logs.txt", max_lines=800)
    decisions_csv = summarize_csv(run_dir / "decisions.csv", max_rows=40)
    trades_csv = summarize_csv(run_dir / "trades.csv", max_rows=40)
    equity_csv = summarize_csv(run_dir / "equity.csv", max_rows=80)

    manifest_txt = _repo_manifest(repo_root)

    prompt = _build_prompt(
        requirements_yaml=requirements_yaml,
        metrics_json=metrics_json,
        logs_txt=logs_txt,
        decisions_csv=decisions_csv,
        trades_csv=trades_csv,
        equity_csv=equity_csv,
        manifest_txt=manifest_txt,
    )

    provider = (settings.codegen_provider or "openai").lower().strip()
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        client = OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )
        data = client.generate_json(
            system=SYSTEM,
            user=prompt,
            schema=PROPOSAL_SCHEMA,
            schema_name="proposal",
            temperature=0.2,
        )
    elif provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        client = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
        text = client.generate_text(prompt=prompt, system=SYSTEM, temperature=0.2)
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported CODEGEN_PROVIDER: {provider}")

    _validate_proposal_paths(data)

    proposal_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prop_dir = repo_root / "proposals" / proposal_id
    prop_dir.mkdir(parents=True, exist_ok=True)

    (prop_dir / "proposal.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (prop_dir / "metrics.json").write_text(metrics_json, encoding="utf-8")
    (prop_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    files_dir = prop_dir / "files"
    files_dir.mkdir(exist_ok=True)

    for ch in (data.get("changes") or []):
        rel = str(ch["path"]).lstrip("/").replace("\\", "/")
        target = files_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ch["content"], encoding="utf-8")

    return ProposalResult(proposal_id=proposal_id, proposal_dir=prop_dir)
