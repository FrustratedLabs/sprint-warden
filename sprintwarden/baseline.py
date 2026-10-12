"""The ratchet snapshot (``baseline.json``) and human-accepted exceptions
(``removals.json``, ``skips.json``).

An acceptance only applies to baselines taken *before* it was recorded. That
way a removal accepted months ago can't silently exempt a test that was later
re-added and re-baselined, and CI can compare a branch against the main
branch's baseline while still honouring removals a human accepted in the PR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sprintwarden import gitutil
from sprintwarden.config import Paths
from sprintwarden.util import (
    SprintError,
    dumps_json,
    iso_ms,
    parse_iso,
    read_json,
    write_json,
    write_text,
)

SCHEMA = 1


@dataclass
class Baseline:
    created: str
    tests: dict[str, str]  # test id -> "passed" | "skipped"
    reason: str = ""
    sprint: str | None = None
    git: dict[str, Any] = field(default_factory=dict)
    run: str | None = None
    source: str = "working tree"

    @property
    def total(self) -> int:
        return len(self.tests)

    def summary(self) -> dict[str, Any]:
        skipped = sum(1 for o in self.tests.values() if o == "skipped")
        return {
            "created": self.created,
            "reason": self.reason,
            "sprint": self.sprint,
            "run": self.run,
            "total": self.total,
            "skipped": skipped,
            "head": (self.git or {}).get("head"),
            "source": self.source,
        }


def _from_data(data: Any, source: str) -> Baseline:
    if not isinstance(data, dict) or not isinstance(data.get("tests"), dict):
        raise SprintError(f"{source}: not a sprintwarden baseline (missing 'tests')")
    if data.get("schema", SCHEMA) > SCHEMA:
        raise SprintError(
            f"{source}: baseline schema {data['schema']} is newer than this sprintwarden",
            hint="upgrade sprintwarden",
        )
    return Baseline(
        created=str(data.get("created", "")),
        tests={str(k): str(v) for k, v in data["tests"].items()},
        reason=str(data.get("reason", "")),
        sprint=data.get("sprint"),
        git=data.get("git") or {},
        run=data.get("run"),
        source=source,
    )


def load_baseline(paths: Paths) -> Baseline | None:
    data = read_json(paths.baseline)
    return None if data is None else _from_data(data, str(paths.baseline))


def load_baseline_from_ref(paths: Paths, ref: str) -> Baseline | None:
    """The baseline as committed at ``ref`` (e.g. ``origin/main``), for CI."""
    rel = paths.baseline.relative_to(paths.root).as_posix()
    text = gitutil.show_file(paths.root, ref, rel)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SprintError(f"{ref}:{rel}: invalid JSON ({exc})") from exc
    return _from_data(data, f"{ref}:{rel}")


def write_baseline(
    paths: Paths,
    tests: dict[str, str],
    *,
    reason: str,
    sprint: str | None,
    git: dict[str, Any],
    run: str | None,
    created: str | None = None,
) -> Baseline:
    """Write the snapshot: one test per line, sorted, so diffs are reviewable."""
    created = created or iso_ms()
    kept = {k: v for k, v in sorted(tests.items()) if v in ("passed", "skipped")}
    data = {
        "schema": SCHEMA,
        "created": created,
        "reason": reason,
        "sprint": sprint,
        "run": run,
        "git": {"head": git.get("head"), "branch": git.get("branch")},
        "totals": {
            "total": len(kept),
            "passed": sum(1 for v in kept.values() if v == "passed"),
            "skipped": sum(1 for v in kept.values() if v == "skipped"),
        },
        "tests": kept,
    }
    write_json(paths.baseline, data)
    return _from_data(data, str(paths.baseline))


@dataclass
class Acceptance:
    id: str
    reason: str
    by: str
    at: str
    git_head: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "by": self.by,
            "at": self.at,
            "git_head": self.git_head,
        }


def _load_list(path: Path, key: str) -> list[Acceptance]:
    data = read_json(path)
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise SprintError(f'{path}: expected {{"{key}": [...]}}')
    out = []
    for item in data[key]:
        if not isinstance(item, dict) or "id" not in item:
            raise SprintError(f"{path}: every entry needs an 'id'")
        out.append(
            Acceptance(
                id=str(item["id"]),
                reason=str(item.get("reason", "")),
                by=str(item.get("by", "")),
                at=str(item.get("at", "")),
                git_head=item.get("git_head"),
            )
        )
    return out


def _save_list(path: Path, key: str, items: list[Acceptance]) -> None:
    data = {"schema": SCHEMA, key: [a.to_json() for a in items]}
    write_text(path, dumps_json(data))


def load_removals(paths: Paths) -> list[Acceptance]:
    return _load_list(paths.removals, "removals")


def load_skips(paths: Paths) -> list[Acceptance]:
    return _load_list(paths.skips, "skips")


def save_removals(paths: Paths, items: list[Acceptance]) -> None:
    _save_list(paths.removals, "removals", items)


def save_skips(paths: Paths, items: list[Acceptance]) -> None:
    _save_list(paths.skips, "skips", items)


def ensure_files(paths: Paths) -> None:
    if not paths.removals.exists():
        save_removals(paths, [])
    if not paths.skips.exists():
        save_skips(paths, [])


def effective(items: list[Acceptance], baseline: Baseline | None) -> dict[str, Acceptance]:
    """Acceptances that apply to ``baseline``: those recorded at or after it was taken."""
    created = parse_iso(baseline.created) if baseline is not None else None
    if created is None:
        return {a.id: a for a in items}
    out = {}
    for a in items:
        at = parse_iso(a.at)
        if at is None or at >= created:
            out[a.id] = a
    return out


def add(
    items: list[Acceptance], ids: list[str], *, reason: str, by: str, git_head: str | None
) -> list[str]:
    """Record acceptances; re-accepting refreshes the entry. Returns the ids written."""
    at = iso_ms()
    index = {a.id: i for i, a in enumerate(items)}
    for test in ids:
        entry = Acceptance(id=test, reason=reason, by=by, at=at, git_head=git_head)
        if test in index:
            items[index[test]] = entry
        else:
            index[test] = len(items)
            items.append(entry)
    return ids
