"""Stop hooks for other agents (experimental; contracts from each agent's docs
as of 2026-10, see docs/AGENTS_SETUP.md). All share :func:`evaluate_stop`.

- Cursor ``stop``: stdout ``{"followup_message": ...}`` sends the agent back to work.
- Codex ``Stop``: stdout ``{"decision": "block", "reason": ...}`` (stdout must be JSON).
- Gemini CLI ``AfterAgent``: ``{"decision": "deny", "reason": ...}``.
- Copilot ``agentStop``: ``{"decision": "block", "reason": ...}`` / ``{"decision": "allow"}``.
"""

from __future__ import annotations

import os
from pathlib import Path

from sprintwarden.hooks._io import emit_json, eprint, payload_cwd, read_payload
from sprintwarden.hooks.stopcore import evaluate_stop


def _decide(
    cwd: Path, agent: str, *, env_vars: tuple[str, ...], continuing_key: str = "stop_hook_active"
):
    data, key = read_payload()
    if agent == "cursor":
        continuing = int(data.get("loop_count") or 0) > 0
        session = data.get("conversation_id") or "cursor"
        if data.get("status") not in (None, "completed"):
            return data, None  # aborted / errored turns are not "done" claims
    else:
        continuing = bool(data.get(continuing_key))
        session = data.get("session_id") or agent
    decision = evaluate_stop(
        payload_cwd(data, cwd, *env_vars),
        session_id=str(session),
        continuing=continuing,
        trigger=f"hook:{agent}-stop",
        agent=agent,
        env=dict(os.environ),
        event_key=key,
    )
    return data, decision


def cursor_stop(cwd: Path) -> int:
    _, d = _decide(cwd, "cursor", env_vars=("CURSOR_PROJECT_DIR",))
    if d is not None and d.block:
        emit_json({"followup_message": d.reason})
    else:
        if d is not None and d.notice:
            eprint(d.notice)
        emit_json({})
    return 0


def codex_stop(cwd: Path) -> int:
    _, d = _decide(cwd, "codex", env_vars=())
    if d.block:
        emit_json({"decision": "block", "reason": d.reason})
    else:
        if d.notice:
            eprint(d.notice)
        emit_json({})
    return 0


def gemini_after_agent(cwd: Path) -> int:
    _, d = _decide(cwd, "gemini-cli", env_vars=("GEMINI_PROJECT_DIR",))
    if d.block:
        emit_json({"decision": "deny", "reason": d.reason})
    else:
        if d.notice:
            eprint(d.notice)
        emit_json({})
    return 0


def copilot_agent_stop(cwd: Path) -> int:
    _, d = _decide(cwd, "copilot", env_vars=())
    if d.block:
        emit_json({"decision": "block", "reason": d.reason})
    else:
        if d.notice:
            eprint(d.notice)
        emit_json({"decision": "allow"})
    return 0
