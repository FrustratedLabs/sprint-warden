"""Install hooks for each agent (and git). Every installer merges into the
agent's existing config file and is idempotent.

Claude Code and git are the supported, tested integrations. Cursor, Codex,
Gemini CLI and Copilot stop hooks are experimental: their hook APIs are young
and change often (see docs/AGENTS_SETUP.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sprintwarden import project
from sprintwarden.config import load_config
from sprintwarden.project import Changes
from sprintwarden.util import SprintError, read_text, write_text

AGENTS = ("claude", "git", "cursor", "codex", "gemini", "copilot")


def _load(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if not text or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SprintError(f"{path}: invalid JSON, not touching it ({exc})") from exc
    if not isinstance(data, dict):
        raise SprintError(f"{path}: expected a JSON object")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2) + "\n")


def _mentions(obj: Any, command: str) -> bool:
    return command in json.dumps(obj)


def install_cursor(root: Path) -> Changes:
    ch = Changes()
    path = root / ".cursor" / "hooks.json"
    data = _load(path)
    cmd = "sprint hook cursor-stop"
    if _mentions(data, cmd):
        ch.skipped.append(".cursor/hooks.json already runs sprintwarden")
        return ch
    data.setdefault("version", 1)
    data.setdefault("hooks", {}).setdefault("stop", []).append({"command": cmd})
    _save(path, data)
    ch.done.append("added a Cursor `stop` hook (.cursor/hooks.json) [experimental]")
    return ch


def install_codex(root: Path) -> Changes:
    ch = Changes()
    path = root / ".codex" / "hooks.json"
    data = _load(path)
    cmd = "sprint hook codex-stop"
    if _mentions(data, cmd):
        ch.skipped.append(".codex/hooks.json already runs sprintwarden")
        return ch
    entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 1800}]}
    data.setdefault("hooks", {}).setdefault("Stop", []).append(entry)
    _save(path, data)
    ch.done.append(
        "added a Codex `Stop` hook (.codex/hooks.json; trust it via /hooks) [experimental]"
    )
    return ch


def install_gemini(root: Path) -> Changes:
    ch = Changes()
    path = root / ".gemini" / "settings.json"
    data = _load(path)
    cmd = "sprint hook gemini-after-agent"
    changed = False
    context = data.setdefault("context", {})
    names = context.get("fileName")
    names = [names] if isinstance(names, str) else list(names or [])
    if "AGENTS.md" not in names:
        context["fileName"] = (
            ["AGENTS.md", *[n for n in names if n != "AGENTS.md"]]
            if names
            else ["AGENTS.md", "GEMINI.md"]
        )
        changed = True
        ch.done.append("Gemini CLI now reads AGENTS.md (.gemini/settings.json context.fileName)")
    if not _mentions(data.get("hooks", {}), cmd):
        entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 1800000}]}
        data.setdefault("hooks", {}).setdefault("AfterAgent", []).append(entry)
        changed = True
        ch.done.append(
            "added a Gemini CLI `AfterAgent` hook (.gemini/settings.json) [experimental]"
        )
    else:
        ch.skipped.append(".gemini/settings.json already runs sprintwarden")
    if changed:
        _save(path, data)
    return ch


def install_copilot(root: Path) -> Changes:
    ch = Changes()
    path = root / ".github" / "hooks" / "sprintwarden.json"
    if path.exists():
        ch.skipped.append(".github/hooks/sprintwarden.json exists")
        return ch
    cmd = "sprint hook copilot-agent-stop"
    data = {
        "version": 1,
        "hooks": {
            "agentStop": [{"type": "command", "bash": cmd, "powershell": cmd, "timeoutSec": 1800}]
        },
    }
    _save(path, data)
    ch.done.append(
        "added a Copilot `agentStop` hook (.github/hooks/sprintwarden.json) [experimental]"
    )
    return ch


def install(root: Path, agent: str, *, with_guard: bool = False) -> Changes:
    agent = agent.lower().strip()
    if agent in ("claude", "claude-code"):
        cfg = load_config(root)
        if with_guard and not cfg.claude_pretool_guard:
            from sprintwarden.config import set_value

            set_value(root, "hooks", "claude_pretool_guard", True)
            cfg = load_config(root)
        return project.merge_claude_settings(
            root, stop=True, session=cfg.claude_session_start, pretool=cfg.claude_pretool_guard
        )
    if agent == "git":
        return project.install_pre_push(root)
    if agent == "cursor":
        return install_cursor(root)
    if agent == "codex":
        return install_codex(root)
    if agent in ("gemini", "gemini-cli"):
        return install_gemini(root)
    if agent == "copilot":
        return install_copilot(root)
    raise SprintError(f"unknown agent {agent!r}", hint="one of: " + ", ".join(AGENTS))


def cmd_install_hooks(env, args):
    from sprintwarden.commands import Outcome

    root = env.root()
    cfg = load_config(root)
    agents = args.agent or (["claude"] if cfg.claude_stop_hook else []) + (
        ["git"] if cfg.git_pre_push else []
    )
    changes = Changes()
    for agent in agents:
        changes.merge(install(root, agent, with_guard=args.with_guard))
    st = env.style
    lines = [f"{st.ok} {d}" for d in changes.done] + [st.dim(f"  · {s}") for s in changes.skipped]
    lines += [f"{st.warn} {w}" for w in changes.warnings]
    return Outcome(
        0,
        {"done": changes.done, "skipped": changes.skipped, "warnings": changes.warnings},
        "\n".join(lines) or "nothing to do",
    )
