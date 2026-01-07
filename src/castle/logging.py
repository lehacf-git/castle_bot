from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """Configure root logger for both console and optional file output."""
    root = logging.getLogger()

    # Remove any existing handlers to avoid duplicates.
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(getattr(logging, (level or "INFO").upper(), logging.INFO))
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # Keep logs readable: silence HTTP client noise unless you *really* want it.
    for noisy in [
        "urllib3",
        "urllib3.connectionpool",
        "requests",
        "httpx",
        "httpcore",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


# Back-compat aliases
configure_logging = setup_logging
init_logging = setup_logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
