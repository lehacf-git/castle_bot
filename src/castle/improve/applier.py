from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

ALLOWED_PREFIXES: Tuple[str, ...] = (
    "src/castle/",
    "tests/",
    "minions/requirements.yaml",
    "README.md",
    ".env.example",
    ".gitignore",
)


@dataclass(frozen=True)
class ApplyResult:
    applied_files: List[str]
    tests_ran: bool
    ok: bool
    message: str


def _safe_rel(rel: str) -> str:
    rel = rel.lstrip("/").replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Unsafe path traversal: {rel}")
    return "/".join(parts)


def _validate_rel_allowed(rel: str) -> None:
    if not rel.startswith(ALLOWED_PREFIXES):
        raise ValueError(
            f"Disallowed path: {rel}\nAllowed prefixes: {', '.join(ALLOWED_PREFIXES)}"
        )


def apply_proposal(*, repo_root: Path, proposal_id: str, run_tests: bool = True) -> ApplyResult:
    proposal_dir = repo_root / "proposals" / proposal_id
    files_dir = proposal_dir / "files"
    if not files_dir.exists():
        return ApplyResult([], False, False, f"Proposal files dir not found: {files_dir}")

    proposed_files = [p for p in files_dir.rglob("*") if p.is_file()]
    if not proposed_files:
        return ApplyResult([], False, False, f"No files found under: {files_dir}")

    applied: List[str] = []
    for src in proposed_files:
        rel = _safe_rel(str(src.relative_to(files_dir)).replace("\\", "/"))
        _validate_rel_allowed(rel)

        dst = repo_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        new_content = src.read_bytes()
        if dst.exists() and dst.read_bytes() == new_content:
            continue

        dst.write_bytes(new_content)
        applied.append(rel)

    tests_ok = True
    ran = False
    msg = f"Applied {len(applied)} file(s)."

    if run_tests:
        ran = True
        try:
            subprocess.run(["python", "-m", "compileall", "src"], cwd=str(repo_root), check=True)
            if shutil.which("pytest") and (repo_root / "tests").exists():
                subprocess.run(["python", "-m", "pytest", "-q", "tests"], cwd=str(repo_root), check=True)
        except subprocess.CalledProcessError as e:
            tests_ok = False
            msg = f"Tests failed: {e}"

    return ApplyResult(applied, ran, tests_ok, msg)
