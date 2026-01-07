from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import yaml

def load_requirements(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"requirements file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def dump_requirements(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)
