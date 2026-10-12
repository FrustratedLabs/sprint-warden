"""Claude Code SessionStart hook: brief the agent so a new, resumed or compacted
session starts with the sprint and ratchet state instead of guessing.

Plain stdout on exit 0 is added to Claude's context.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sprintwarden.config import find_root, load_config
from sprintwarden.hooks._io import payload_cwd, read_payload
from sprintwarden.util import SprintError

_AC = {"satisfied": "done", "failing": "FAILING", "no-tests": "no tests yet"}


def brief(status: dict[str, Any], example: str = "") -> str:
    lines = [
        f"[sprintwarden] {status['project']} is protected by a test ratchet (.sprint/, rules in AGENTS.md)."
    ]
    sp = status.get("sprint")
    if status["mode"] == "sprints":
        if sp:
            lines.append(
                f"Active sprint {sp['id']}: {sp['title']}. Goal: {sp.get('goal') or '(none)'}"
            )
            for a in sp.get("acs_state", []):
                lines.append(f"  {a['id']} [{_AC.get(a['state'], a['state'])}] {a['desc']}")
            if sp.get("out_of_scope"):
                lines.append("  Out of scope: " + ", ".join(sp["out_of_scope"]))
            name = (example or "S01_doesThing").replace("S01", sp["id"])
            lines.append(f"Name new tests with the sprint id, e.g. {name}.")
        else:
            lines.append("No sprint is active. Ask the human before starting feature work.")
    latest = status.get("latest")
    if latest:
        c = latest.get("counts") or {}
        stale = f" (stale: {status['stale']})" if status.get("stale") else ""
        summary = f"Last gate: {str(latest.get('result', '?')).upper()}{stale}"
        bits = [
            f"{c[k]} {k.replace('_', ' ')}"
            for k in ("regressions", "failing", "missing", "new_skips")
            if c.get(k)
        ]
        if bits:
            summary += " — " + ", ".join(bits)
        lines.append(summary)
        for f in (latest.get("failing") or [])[:5]:
            tag = " (REGRESSION)" if f.get("regression") else ""
            lines.append(f"  [{f['sprint']}] {f['id']}{tag}")
    lines.append(
        "Before saying you're done, run `sprint gate` and paste its summary. Never delete, skip, rename or "
        "weaken existing tests. `sprint baseline/close/accept-removal/allow-skip` are human-only."
    )
    return "\n".join(lines)


def run_hook(cwd: Path) -> int:
    data, _ = read_payload()
    root = find_root(payload_cwd(data, cwd, "CLAUDE_PROJECT_DIR"))
    if root is None:
        return 0
    try:
        cfg = load_config(root)
    except SprintError as exc:
        print(f"[sprintwarden] .sprint/config.toml is invalid: {exc}. Ask the human to fix it.")
        return 0
    if not cfg.claude_session_start:
        return 0
    from sprintwarden.commands import project_status
    from sprintwarden.stacks import load_stacks

    stack = load_stacks().get(cfg.stack)
    try:
        status = project_status(cfg)
    except SprintError as exc:
        print(f"[sprintwarden] could not read project state: {exc}")
        return 0
    sys.stdout.write(brief(status, stack.example_test if stack else "") + "\n")
    return 0
