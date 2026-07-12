"""Small local environment loader for development without exposing values."""

from __future__ import annotations

import os
from pathlib import Path


def load_local_environment(path: Path | None = None) -> None:
    source = path or Path(".env.local")
    if not source.is_file():
        return
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)
