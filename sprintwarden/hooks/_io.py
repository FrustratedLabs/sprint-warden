"""Shared stdin/stdout helpers for hook entry points."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def read_payload() -> tuple[dict[str, Any], str]:
    """Parse the hook JSON on stdin (empty/invalid input is an empty payload)."""
    try:
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    key = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16] if raw else ""
    return data, key


def payload_cwd(data: dict[str, Any], fallback: Path, *env_vars: str) -> Path:
    for candidate in (data.get("cwd"), *(os.environ.get(v) for v in env_vars)):
        if isinstance(candidate, str) and candidate and Path(candidate).is_dir():
            return Path(candidate)
    roots = data.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and Path(roots[0]).is_dir():
        return Path(roots[0])
    return fallback


def emit_json(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()


def eprint(text: str) -> None:
    sys.stderr.write(text.rstrip("\n") + "\n")
    sys.stderr.flush()
