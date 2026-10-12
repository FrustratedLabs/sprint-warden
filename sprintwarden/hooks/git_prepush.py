"""Git pre-push hook. Chains to the hook that was installed before
(``pre-push.local*``), then blocks the push if the gate fails.

Bypass once with ``SPRINT_SKIP=1 git push``; the bypass is recorded in
``.sprint/runs/`` as ``"bypassed": true``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from sprintwarden import gitutil
from sprintwarden.config import find_root, load_config
from sprintwarden.gate import load_full, record_bypass, run_gate
from sprintwarden.report import Style, render_gate
from sprintwarden.util import SprintError

ZERO = "0" * 40


def _chained(root: Path) -> list[Path]:
    hooks = gitutil.hooks_dir(root)
    if hooks is None or not hooks.is_dir():
        return []
    return sorted(p for p in hooks.glob("pre-push.local*") if p.is_file())


def _run_chained(path: Path, argv: list[str], stdin: str) -> int:
    if os.name == "nt" or not os.access(path, os.X_OK):
        sh = shutil.which("sh") or "sh"
        cmd = [sh, str(path), *argv]
    else:
        cmd = [str(path), *argv]
    try:
        return subprocess.run(cmd, input=stdin, text=True, check=False).returncode
    except OSError as exc:
        print(f"sprintwarden: could not run chained hook {path.name}: {exc}", file=sys.stderr)
        return 1


def _only_deletions(stdin: str) -> bool:
    lines = [line.split() for line in stdin.splitlines() if line.strip()]
    return bool(lines) and all(len(p) >= 2 and set(p[1]) <= {"0"} for p in lines)


def run_hook(cwd: Path, argv: list[str], stdin: str) -> int:
    root = find_root(cwd)
    if root is None:
        return 0
    for hook in _chained(root):
        code = _run_chained(hook, argv, stdin)
        if code != 0:
            return code
    try:
        cfg = load_config(root)
    except SprintError as exc:
        print(f"sprintwarden: push blocked: {exc}", file=sys.stderr)
        return 1
    if not cfg.git_pre_push:
        return 0
    if os.environ.get("SPRINT_SKIP", "").strip().lower() in ("1", "true", "yes"):
        path = record_bypass(cfg, trigger="hook:pre-push")
        print(
            f"sprintwarden: gate BYPASSED with SPRINT_SKIP=1 (recorded in {path.relative_to(root).as_posix()})",
            file=sys.stderr,
        )
        return 0
    if _only_deletions(stdin):
        return 0
    style = Style.for_stream(sys.stderr)
    fp = gitutil.fingerprint(root)
    full = load_full(cfg)
    if fp and full and full.get("fingerprint") == fp and full.get("result") == "pass":
        print("sprintwarden: gate already passed for this exact tree; pushing.", file=sys.stderr)
        return 0
    if gitutil.is_dirty(root):
        print(
            "sprintwarden: note: testing the working tree, which has uncommitted changes.",
            file=sys.stderr,
        )
    result = run_gate(cfg, trigger="hook:pre-push")
    print(render_gate(result.record, style), file=sys.stderr)
    if not result.passed:
        print(
            "sprintwarden: push blocked. Fix the failures above, or bypass once with "
            "`SPRINT_SKIP=1 git push` (recorded).",
            file=sys.stderr,
        )
        return 1
    return 0
