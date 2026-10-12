"""Hook entry points: ``sprint hook <name>`` (and ``sprint gate --hook``)."""

from __future__ import annotations

import sys
from typing import Any


def cmd_hook(env: Any, args: Any):
    from sprintwarden.commands import Outcome

    name = args.name
    cwd = env.cwd
    if name == "claude-stop":
        from sprintwarden.hooks.claude_stop import run_hook

        return Outcome(run_hook(cwd))
    if name in ("claude-pretool", "pretool"):
        from sprintwarden.hooks.claude_pretool import run_hook

        return Outcome(run_hook(cwd))
    if name == "session-start":
        from sprintwarden.hooks.claude_session import run_hook

        return Outcome(run_hook(cwd))
    if name == "pre-push":
        from sprintwarden.hooks.git_prepush import run_hook

        stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
        return Outcome(run_hook(cwd, list(args.hook_args), stdin))
    from sprintwarden.hooks import other_agents

    handler = {
        "cursor-stop": other_agents.cursor_stop,
        "codex-stop": other_agents.codex_stop,
        "gemini-after-agent": other_agents.gemini_after_agent,
        "copilot-agent-stop": other_agents.copilot_agent_stop,
    }[name]
    return Outcome(handler(cwd))
