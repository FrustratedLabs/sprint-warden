"""Run records: one small JSON file per gate run, plus ``latest.json``.

Runs are sharded by month (``runs/2026-10/20261012T103105Z-3fa2.json``) so a
project with years of history doesn't end up with one giant directory, and
``[history] keep`` can cap the count. Runs marked as milestones (baselines,
sprint closes) are never pruned.
"""

from __future__ import annotations

import datetime as dt
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sprintwarden.config import Paths
from sprintwarden.util import atomic_write_text, dumps_json, read_json, write_json

SCHEMA = 1
LIST_CAP = 200  # failing/missing/new_skips entries kept in latest.json
HISTORY_CAP = 50  # ...and in each committed history file (counts stay exact)


def new_run_id() -> str:
    """``20261012T103105123Z-3fa2``: sorts chronologically (to the millisecond)."""
    now = dt.datetime.now(dt.UTC)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z-" + secrets.token_hex(2)


def run_file(paths: Paths, run_id: str) -> Path:
    month = f"{run_id[:4]}-{run_id[4:6]}"
    return paths.runs / month / f"{run_id}.json"


def iter_run_files(paths: Paths) -> Iterator[Path]:
    """Run files, newest first."""
    if not paths.runs.is_dir():
        return
    months = sorted((p for p in paths.runs.iterdir() if p.is_dir()), reverse=True)
    for month in months:
        yield from sorted(month.glob("*.json"), reverse=True)
    # tolerate flat layouts (older versions, hand-copied files)
    yield from sorted(paths.runs.glob("*.json"), reverse=True)


def list_runs(paths: Paths, limit: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in iter_run_files(paths):
        try:
            data = read_json(path)
        except Exception:
            continue
        if isinstance(data, dict):
            out.append(data)
        if limit is not None and len(out) >= limit:
            break
    return out


def load_run(paths: Paths, run_id: str) -> dict[str, Any] | None:
    path = run_file(paths, run_id)
    data = read_json(path) if path.is_file() else read_json(paths.runs / f"{run_id}.json")
    return data if isinstance(data, dict) else None


def load_latest(paths: Paths) -> dict[str, Any] | None:
    """latest.json, or (fresh clone, latest.json not committed) the newest run file."""
    try:
        data = read_json(paths.latest)
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    newest = list_runs(paths, 5)
    return next((r for r in newest if not r.get("bypassed")), None)


def cap_lists(record: dict[str, Any], cap: int = LIST_CAP) -> dict[str, Any]:
    """Copy of ``record`` with long lists trimmed for committed files."""
    out = dict(record)
    truncated = {}
    for key in ("failing", "missing", "new_skips", "new_tests"):
        items = record.get(key) or []
        if len(items) > cap:
            out[key] = items[:cap]
            truncated[key] = len(items) - cap
    if truncated:
        out["truncated"] = truncated
    return out


def history_record(record: dict[str, Any]) -> dict[str, Any]:
    """The slim form stored in ``runs/``: capped lists, per-AC counts instead of test lists.

    Stop hooks can run the gate many times a day for years, so committed history
    must stay small; ``latest.json`` keeps the detail.
    """
    out = cap_lists(record, HISTORY_CAP)
    out.pop("new_tests", None)
    out["acs"] = [
        {
            "sprint": a.get("sprint"),
            "id": a.get("id"),
            "state": a.get("state"),
            "matched": len(a.get("tests") or []) + int(a.get("tests_truncated") or 0),
            "failing": sum(1 for t in a.get("tests") or [] if t.get("outcome") != "passed"),
        }
        for a in record.get("acs") or []
    ]
    return out


def write_run(
    paths: Paths, record: dict[str, Any], *, latest_extra: dict[str, Any] | None = None
) -> Path:
    path = run_file(paths, record["id"])
    atomic_write_text(path, dumps_json(history_record(record), compact=True) + "\n")
    latest = cap_lists(record)
    latest.pop("new_tests", None)  # can be huge on the first run; counts are kept
    if latest_extra:
        latest.update(latest_extra)
    write_json(paths.latest, latest)
    return path


def mark_milestone(paths: Paths, run_id: str, label: str) -> None:
    path = run_file(paths, run_id)
    data = read_json(path) if path.is_file() else None
    if isinstance(data, dict):
        data["milestone"] = label
        atomic_write_text(path, dumps_json(data, compact=True) + "\n")
    latest = load_latest(paths)
    if latest and latest.get("id") == run_id:
        latest["milestone"] = label
        write_json(paths.latest, latest)


def prune(paths: Paths, keep: int) -> int:
    """Delete the oldest non-milestone runs beyond ``keep``. Returns the number deleted."""
    if keep <= 0:
        return 0
    files = list(iter_run_files(paths))
    if len(files) <= keep:
        return 0
    deleted = 0
    for path in files[keep:]:
        try:
            data = read_json(path)
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("milestone"):
            continue
        try:
            os.unlink(path)
            deleted += 1
        except OSError:
            continue
    for month in paths.runs.iterdir():
        if month.is_dir() and not any(month.iterdir()):
            try:
                month.rmdir()
            except OSError:
                pass
    return deleted
