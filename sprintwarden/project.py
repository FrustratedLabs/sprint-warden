"""Project setup: ``.sprint/``, agent instruction files, hooks, ``.gitignore``.

Every step is idempotent and never overwrites user content: managed blocks are
fenced with markers, JSON settings are merged, existing git hooks are chained.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from sprintwarden import gitutil, registry
from sprintwarden.config import SPRINT_DIR, Config, Paths
from sprintwarden.stacks import Stack
from sprintwarden.util import SprintError, read_text, today, toml_literal, write_text

BEGIN = "<!-- sprintwarden:begin (managed by `sprint init`; edit outside this block) -->"
END = "<!-- sprintwarden:end -->"
HOOK_MARKER = "sprintwarden-managed-hook"

STOP_CMD = "sprint gate --hook"
SESSION_CMD = "sprint hook session-start"
PRETOOL_CMD = "sprint hook pretool"
PRETOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"


@dataclass
class Changes:
    """What a setup step did, for the init report."""

    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: Changes) -> Changes:
        self.done += other.done
        self.skipped += other.skipped
        self.warnings += other.warnings
        return self


def template(name: str) -> str:
    return resources.files("sprintwarden").joinpath("templates", name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- config


def render_config(
    *,
    name: str,
    key: str,
    mode: str,
    stack: Stack,
    command: str,
    reports: list[str],
    current: str,
) -> str:
    env = ""
    if stack.env:
        env = "\n[test.env]\n" + "".join(f"{k} = {toml_literal(v)}\n" for k, v in stack.env.items())
    windows = (
        f"command_windows = {toml_literal(stack.command_windows)}\n"
        if stack.command_windows
        else ""
    )
    sprint_section = f"""
[sprint]                            # ignored in ratchet-only mode
current = {toml_literal(current)}
# id_pattern = '(?i)(?<![A-Za-z0-9])S(\\d{{2,}})(?=[_\\]\\s:.()\\[/-]|$)'   # group 1 = sprint number
"""
    return f"""# sprintwarden config. The only stack-specific file in .sprint/.
# Docs: https://github.com/sprintwarden/sprintwarden#configuration

[project]
name = {toml_literal(name)}
key  = {toml_literal(key)}                       # short key for the dashboard
mode = {toml_literal(mode)}                    # "sprints" | "ratchet-only"
stack = {toml_literal(stack.name)}

[test]
command  = {toml_literal(command)}         # any shell command, run from the repo root
{windows}reports  = {toml_literal(reports)}
timeout_minutes = 30
clean_reports_before_run = true     # deletes stale, untracked JUnit XML before each run
sources = {toml_literal(stack.sources)}   # test files, for the optional PreToolUse guard
{env}{sprint_section}
[gate]
fail_on_new_skips = true
fail_on_missing_tests = true
require_current_sprint_tests = true
fail_on_runner_error = true         # runner exits non-zero but no test failed -> fail

[hooks]
claude_stop_hook = true
claude_session_start = true         # brief the agent with `sprint status` at session start
claude_pretool_guard = false        # warn when an edit deletes or skips tests
pretool_mode = "warn"               # "warn" | "block"
stop_hook_max_blocks = 3            # then let the agent stop and tell the human
git_pre_push = true

[history]
in_git = true                       # commit .sprint/runs/ (small JSON files)
latest_in_git = false               # latest.json is a local cache; committing it blocks branch switches
keep = 0                            # max run files to keep (0 = unlimited); milestones are kept

[ui]
allure_url = ""                     # optional: link out for per-test history
"""


# --------------------------------------------------------------------------- agent files


def _render_agents(cfg: Config, example: str) -> str:
    name = "AGENTS.md" if cfg.sprints_mode else "AGENTS.ratchet.md"
    body = template(name)
    sprint = cfg.sprint_current or "S01"
    body = body.replace("{{SPRINT}}", sprint)
    body = body.replace("{{EXAMPLE}}", example.replace("S01", sprint))
    commands = " && ".join(s.command for s in cfg.suites)
    body = body.replace("{{TEST_COMMAND}}", commands)
    return f"{BEGIN}\n{body.rstrip()}\n{END}\n"


def write_agents_md(
    cfg: Config, example: str = "S01_doesThing", *, refresh: bool = True
) -> Changes:
    """Insert or refresh the managed block in AGENTS.md. Content outside it is never touched."""
    ch = Changes()
    path = cfg.root / "AGENTS.md"
    block = _render_agents(cfg, example)
    text = read_text(path)
    if text is None:
        write_text(path, block)
        ch.done.append("created AGENTS.md (agent rules)")
        return ch
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        current = text[start:end] + "\n"
        if current == block or not refresh:
            ch.skipped.append("AGENTS.md already has the sprintwarden rules")
            return ch
        rest = text[end:]
        rest = rest[1:] if rest.startswith("\n") else rest
        write_text(path, text[:start] + block + rest)
        ch.done.append("refreshed the sprintwarden block in AGENTS.md")
        return ch
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    write_text(path, text + sep + block)
    ch.done.append("appended the sprintwarden rules to AGENTS.md")
    return ch


def write_claude_md(root: Path) -> Changes:
    ch = Changes()
    path = root / "CLAUDE.md"
    text = read_text(path)
    if text is None:
        write_text(path, "@AGENTS.md\n")
        ch.done.append("created CLAUDE.md (imports AGENTS.md)")
        return ch
    if re.search(r"(?m)^\s*@AGENTS\.md\s*$", text):
        ch.skipped.append("CLAUDE.md already imports AGENTS.md")
        return ch
    sep = "" if text.endswith("\n") or not text else "\n"
    write_text(path, text + sep + "\n@AGENTS.md\n")
    ch.done.append("appended `@AGENTS.md` to CLAUDE.md")
    return ch


# --------------------------------------------------------------------------- Claude hooks


def _load_json_obj(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SprintError(f"{path}: invalid JSON, not touching it ({exc})") from exc
    if not isinstance(data, dict):
        raise SprintError(f"{path}: expected a JSON object")
    return data


def _has_command(entries: list[Any], command: str) -> bool:
    for entry in entries if isinstance(entries, list) else []:
        for hook in (entry or {}).get("hooks", []) if isinstance(entry, dict) else []:
            if isinstance(hook, dict) and command in str(hook.get("command", "")):
                return True
    return False


def merge_claude_settings(
    root: Path, *, stop: bool = True, session: bool = True, pretool: bool = False
) -> Changes:
    """Merge our hooks into ``.claude/settings.json``, preserving everything else."""
    ch = Changes()
    path = root / ".claude" / "settings.json"
    data = _load_json_obj(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SprintError(f"{path}: 'hooks' must be an object")
    wanted = []
    if stop:
        wanted.append(("Stop", None, STOP_CMD, 1800))
    if session:
        wanted.append(("SessionStart", None, SESSION_CMD, 30))
    if pretool:
        wanted.append(("PreToolUse", PRETOOL_MATCHER, PRETOOL_CMD, 30))
    changed = False
    for event, matcher, command, timeout in wanted:
        entries = hooks.setdefault(event, [])
        if _has_command(entries, command):
            ch.skipped.append(f".claude/settings.json already runs `{command}` on {event}")
            continue
        entry: dict[str, Any] = {
            "hooks": [{"type": "command", "command": command, "timeout": timeout}]
        }
        if matcher:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
        changed = True
        ch.done.append(f"added `{command}` as a Claude Code {event} hook")
    if changed:
        write_text(path, json.dumps(data, indent=2) + "\n")
    return ch


# --------------------------------------------------------------------------- git pre-push


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _hook_script() -> str:
    python = Path(sys.executable).as_posix()
    return f"""#!/bin/sh
# {HOOK_MARKER}: pre-push. The logic lives in Python (`sprint hook pre-push`).
# It chains to the hook that was here before (pre-push.local), then runs the gate.
# Bypass once with: SPRINT_SKIP=1 git push   (recorded as "bypassed" in .sprint/runs/)
if command -v sprint >/dev/null 2>&1; then
  exec sprint hook pre-push "$@"
fi
exec {_sh_quote(python)} -m sprintwarden hook pre-push "$@"
"""


def install_pre_push(root: Path) -> Changes:
    ch = Changes()
    if not gitutil.is_repo(root):
        ch.skipped.append("not a git repository: pre-push hook not installed")
        return ch
    hooks_path = gitutil.hooks_path_config(root) or ""
    if ".husky" in hooks_path.replace("\\", "/"):
        return _install_husky(root, ch)
    hooks = gitutil.hooks_dir(root)
    if hooks is None:
        ch.warnings.append("could not locate the git hooks directory")
        return ch
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-push"
    script = _hook_script()
    existing = read_text(target) if target.exists() else None
    if existing is not None and HOOK_MARKER in existing:
        if existing == script:
            ch.skipped.append("pre-push hook already installed")
            return ch
        write_text(target, script)
        _make_executable(target)
        ch.done.append("updated the sprintwarden pre-push hook")
        return ch
    if existing is not None:
        chained = hooks / "pre-push.local"
        n = 1
        while chained.exists():
            chained = hooks / f"pre-push.local.{n}"
            n += 1
        os.replace(target, chained)
        ch.done.append(f"moved the existing pre-push hook to {chained.name} (it still runs first)")
    write_text(target, script)
    _make_executable(target)
    ch.done.append(f"installed the pre-push hook ({gitutil_rel(target, root)})")
    return ch


def _install_husky(root: Path, ch: Changes) -> Changes:
    target = root / ".husky" / "pre-push"
    line = 'sprint hook pre-push "$@"'
    text = read_text(target) or ""
    if line in text:
        ch.skipped.append(".husky/pre-push already runs sprintwarden")
        return ch
    sep = "" if not text or text.endswith("\n") else "\n"
    write_text(target, f"{text}{sep}# {HOOK_MARKER}\n{line}\n")
    _make_executable(target)
    ch.done.append("added sprintwarden to .husky/pre-push (husky manages core.hooksPath)")
    return ch


def gitutil_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _make_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


# --------------------------------------------------------------------------- gitignore


GITIGNORE_HEADER = "# sprintwarden: gate scratch space and hook state"


def update_gitignore(
    root: Path, *, history_in_git: bool = True, latest_in_git: bool = False
) -> Changes:
    ch = Changes()
    path = root / ".gitignore"
    text = read_text(path) or ""
    existing = {line.strip() for line in text.splitlines()}
    wanted = [f"{SPRINT_DIR}/out/"]
    if not latest_in_git:
        wanted.append(f"{SPRINT_DIR}/latest.json")
    if not history_in_git:
        wanted.append(f"{SPRINT_DIR}/runs/")
    missing = [w for w in wanted if w not in existing and w.rstrip("/") not in existing]
    if not missing:
        ch.skipped.append(".gitignore already ignores .sprint/out/")
        return ch
    block = (
        ("" if GITIGNORE_HEADER in text else GITIGNORE_HEADER + "\n") + "\n".join(missing) + "\n"
    )
    sep = "" if not text or text.endswith("\n") else "\n"
    write_text(path, text + sep + block)
    ch.done.append("updated .gitignore (" + ", ".join(missing) + ")")
    return ch


def update_gitattributes(root: Path) -> Changes:
    """Collapse generated run records in GitHub diffs; the baseline stays visible."""
    ch = Changes()
    path = root / ".gitattributes"
    text = read_text(path) or ""
    lines = [
        f"{SPRINT_DIR}/runs/** linguist-generated=true",
        f"{SPRINT_DIR}/latest.json linguist-generated=true",
    ]
    missing = [line for line in lines if line not in text]
    if not missing:
        return ch
    sep = "" if not text or text.endswith("\n") else "\n"
    write_text(path, text + sep + "\n".join(missing) + "\n")
    ch.done.append("updated .gitattributes (run records collapse in PR diffs)")
    return ch


# --------------------------------------------------------------------------- .sprint/


def write_sprint_skeleton(paths: Paths) -> Changes:
    ch = Changes()
    paths.dir.mkdir(parents=True, exist_ok=True)
    (paths.out).mkdir(exist_ok=True)
    readme = paths.dir / "README.md"
    if not readme.exists():
        write_text(readme, template("sprint-dir-README.md"))
    from sprintwarden import baseline as bl

    bl.ensure_files(paths)
    return ch


def write_first_sprint(paths: Paths, title: str, example: str) -> Changes:
    from sprintwarden.sprintfile import render_sprint, sprint_filename, sprint_files

    ch = Changes()
    paths.sprints.mkdir(parents=True, exist_ok=True)
    if sprint_files(paths.sprints):
        ch.skipped.append("sprint files already exist")
        return ch
    path = paths.sprints / sprint_filename("S01", title)
    write_text(path, render_sprint("S01", title, status="active", started=today(), example=example))
    ch.done.append(f"created {path.relative_to(paths.root).as_posix()} (active)")
    return ch


def register_project(root: Path) -> Changes:
    ch = Changes()
    try:
        if registry.register(root):
            ch.done.append(f"registered in {registry.registry_path()}")
        else:
            ch.skipped.append("already in the global registry")
    except (OSError, SprintError) as exc:
        ch.warnings.append(f"could not update the global registry: {exc}")
    return ch
