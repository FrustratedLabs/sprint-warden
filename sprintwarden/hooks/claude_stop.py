"""Claude Code Stop hook (``sprint gate --hook``). Kept thin: the decision lives in
:mod:`sprintwarden.hooks.stopcore`.

Contract (code.claude.com/docs/en/hooks): exit 2 blocks the stop and feeds
stderr to Claude; exit 0 allows it, and a JSON ``systemMessage`` on stdout is
shown to the user.
"""

from __future__ import annotations

import os
from pathlib import Path

from sprintwarden.hooks._io import emit_json, eprint, payload_cwd, read_payload
from sprintwarden.hooks.stopcore import evaluate_stop


def run_hook(cwd: Path) -> int:
    data, key = read_payload()
    decision = evaluate_stop(
        payload_cwd(data, cwd, "CLAUDE_PROJECT_DIR"),
        session_id=str(data.get("session_id") or "claude"),
        continuing=bool(data.get("stop_hook_active")),
        trigger="hook:claude-stop",
        agent="claude-code",
        env=dict(os.environ),
        event_key=key,
    )
    if decision.block:
        eprint(decision.reason)
        return 2
    if decision.notice:
        eprint(decision.notice)
        emit_json({"systemMessage": decision.notice})
    return 0
