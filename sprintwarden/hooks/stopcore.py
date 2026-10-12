"""The decision behind every agent "stop" hook (Claude Code, Cursor, Codex,
Gemini CLI, Copilot). Adapters only translate input/output formats.

- No project, or SPRINT_SKIP=1: allow.
- Nothing changed since the last gate run (same fingerprint): reuse its result,
  so a pass is instant and a failure is replayed without re-running tests.
- Otherwise run the gate.
- On failure, block with an agent-actionable report, at most
  ``stop_hook_max_blocks`` times in a row per session; then allow and tell the
  human, so the agent never loops forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sprintwarden import gitutil, runs
from sprintwarden.config import Config, find_root, load_config
from sprintwarden.gate import run_gate
from sprintwarden.report import render_agent
from sprintwarden.util import SprintError, read_json, write_json

MAX_SESSIONS = 30
# The same hook installed twice (project settings + plugin) fires twice for one
# stop, almost simultaneously and with an identical payload. A real retry needs a
# model turn, so it can't arrive this fast.
DUPLICATE_WINDOW_S = 2.0


@dataclass
class StopDecision:
    block: bool
    reason: str = ""  # for the agent, when blocking
    notice: str = ""  # for the human
    record: dict[str, Any] | None = None
    cached: bool = False


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in ("0", "false", "no", "off")


def _load_state(cfg: Config) -> dict[str, Any]:
    try:
        data = read_json(cfg.paths.hook_state)
    except SprintError:
        data = None
    return data if isinstance(data, dict) else {}


def _save_state(cfg: Config, state: dict[str, Any]) -> None:
    sessions = state.get("sessions", {})
    if len(sessions) > MAX_SESSIONS:
        newest = sorted(sessions.items(), key=lambda kv: kv[1].get("last", 0), reverse=True)
        state["sessions"] = dict(newest[:MAX_SESSIONS])
    try:
        write_json(cfg.paths.hook_state, state)
    except OSError:
        pass


def _cached_record(
    cfg: Config, state: dict[str, Any], fingerprint: str | None
) -> dict[str, Any] | None:
    """The latest run record if it describes exactly the current tree."""
    if not fingerprint:
        return None
    latest = runs.load_latest(cfg.paths)
    if not latest or not latest.get("ran", True):
        return None
    if state.get("fingerprint") == fingerprint and state.get("record_id") == latest.get("id"):
        return latest
    if (latest.get("git") or {}).get("fingerprint") == fingerprint:
        return latest  # e.g. the human just ran `sprint gate`
    return None


def evaluate_stop(
    cwd: Path,
    *,
    session_id: str,
    continuing: bool,
    trigger: str,
    agent: str,
    env: dict[str, str],
    event_key: str = "",
) -> StopDecision:
    """``event_key`` is a hash of the hook payload: an identical payload within
    ``DUPLICATE_WINDOW_S`` is the same stop event seen by a second copy of the
    hook, and is only counted once by the loop guard."""
    root = find_root(cwd)
    if root is None:
        return StopDecision(False)
    if _truthy(env.get("SPRINT_SKIP")):
        return StopDecision(False, notice="sprintwarden: stop hook skipped (SPRINT_SKIP=1)")
    try:
        cfg = load_config(root)
    except SprintError as exc:
        # Don't let a broken config become a way out of the gate.
        return _block_with_guard(
            None,
            root,
            session_id,
            continuing,
            reason=f"sprintwarden: .sprint/config.toml is invalid ({exc}). Restore it; don't edit .sprint/.",
        )
    if trigger == "hook:claude-stop" and not cfg.claude_stop_hook:
        return StopDecision(False)

    state = _load_state(cfg)
    fingerprint = gitutil.fingerprint(cfg.root)
    record = _cached_record(cfg, state, fingerprint)
    cached = record is not None
    if record is None:
        result = run_gate(cfg, trigger=trigger, agent=agent)
        record = result.record
        state["fingerprint"] = gitutil.fingerprint(cfg.root)  # post-run state
        state["record_id"] = record["id"]
        state["result"] = record["result"]
    sessions = state.setdefault("sessions", {})
    sess = sessions.setdefault(session_id or "default", {"blocks": 0, "last": 0.0})
    now = time.time()

    if record.get("result") == "pass":
        sess.update(blocks=0, last=now)
        _save_state(cfg, state)
        return StopDecision(False, record=record, cached=cached)

    if not continuing:
        sess["blocks"] = 0
    duplicate = (
        bool(event_key)
        and sess.get("event") == event_key
        and sess.get("blocks", 0) > 0
        and now - float(sess.get("last", 0)) < DUPLICATE_WINDOW_S
    )
    if sess.get("blocks", 0) >= cfg.stop_hook_max_blocks and continuing:
        sess["last"] = now
        _save_state(cfg, state)
        return StopDecision(
            False,
            notice=(
                f"sprintwarden: the gate is still failing after {sess['blocks']} attempts, so the agent "
                "was allowed to stop. Run `sprint gate` to see what's broken."
            ),
            record=record,
            cached=cached,
        )
    if not duplicate:
        sess["blocks"] = int(sess.get("blocks", 0)) + 1
    sess["event"] = event_key
    sess["last"] = now
    _save_state(cfg, state)
    reason = render_agent(record)
    if cached:
        reason += "\n(Nothing changed since this gate run, so it was not re-run.)"
    return StopDecision(True, reason=reason, record=record, cached=cached)


def _block_with_guard(
    cfg, root: Path, session_id: str, continuing: bool, *, reason: str
) -> StopDecision:
    state_path = root / ".sprint" / "out" / "hook-state.json"
    try:
        state = read_json(state_path) or {}
    except SprintError:
        state = {}
    sess = state.setdefault("sessions", {}).setdefault(
        session_id or "default", {"blocks": 0, "last": 0.0}
    )
    if not continuing:
        sess["blocks"] = 0
    if sess["blocks"] >= 3 and continuing:
        return StopDecision(False, notice=reason)
    sess["blocks"] += 1
    sess["last"] = time.time()
    try:
        write_json(state_path, state)
    except OSError:
        pass
    return StopDecision(True, reason=reason)
