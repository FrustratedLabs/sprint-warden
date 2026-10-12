"""Locate a project and load ``.sprint/config.toml``.

The config is the only stack-specific file in a project. Everything else under
``.sprint/`` is plain JSON or Markdown written by the CLI.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sprintwarden.attribution import DEFAULT_ID_PATTERN, normalize_sprint_id
from sprintwarden.util import SprintError, read_text, toml_set, write_text

SPRINT_DIR = ".sprint"
CONFIG_NAME = "config.toml"
MODES = ("sprints", "ratchet-only")


@dataclass(frozen=True)
class Paths:
    """Every file location under ``.sprint/`` in one place."""

    root: Path

    @property
    def dir(self) -> Path:
        return self.root / SPRINT_DIR

    @property
    def config(self) -> Path:
        return self.dir / CONFIG_NAME

    @property
    def sprints(self) -> Path:
        return self.dir / "sprints"

    @property
    def baseline(self) -> Path:
        return self.dir / "baseline.json"

    @property
    def removals(self) -> Path:
        return self.dir / "removals.json"

    @property
    def skips(self) -> Path:
        return self.dir / "skips.json"

    @property
    def runs(self) -> Path:
        return self.dir / "runs"

    @property
    def latest(self) -> Path:
        return self.dir / "latest.json"

    @property
    def out(self) -> Path:
        return self.dir / "out"

    @property
    def latest_full(self) -> Path:
        """Uncapped results of the latest run (gitignored)."""
        return self.out / "latest-full.json"

    @property
    def hook_state(self) -> Path:
        return self.out / "hook-state.json"

    @property
    def lock(self) -> Path:
        return self.out / "gate.lock"

    @property
    def runner_log(self) -> Path:
        return self.out / "runner.log"


@dataclass
class Suite:
    name: str
    command: str
    reports: list[str]
    cwd: str = ""
    timeout_minutes: float = 30.0
    env: dict[str, str] = field(default_factory=dict)
    command_windows: str = ""

    def effective_command(self) -> str:
        if os.name == "nt" and self.command_windows:
            return self.command_windows
        return self.command


@dataclass
class Config:
    root: Path
    raw: dict[str, Any]
    name: str
    key: str
    mode: str
    stack: str
    suites: list[Suite]
    clean_reports_before_run: bool
    sources: list[str]
    sprint_current: str
    id_pattern: str
    fail_on_new_skips: bool
    fail_on_missing_tests: bool
    require_current_sprint_tests: bool
    fail_on_runner_error: bool
    claude_stop_hook: bool
    claude_session_start: bool
    claude_pretool_guard: bool
    pretool_mode: str
    stop_hook_max_blocks: int
    git_pre_push: bool
    history_in_git: bool
    history_keep: int
    allure_url: str
    warnings: list[str] = field(default_factory=list)

    @property
    def paths(self) -> Paths:
        return Paths(self.root)

    @property
    def sprints_mode(self) -> bool:
        return self.mode == "sprints"

    @property
    def report_globs(self) -> list[str]:
        globs: list[str] = []
        for suite in self.suites:
            for g in suite.reports:
                if g not in globs:
                    globs.append(g)
        return globs


def find_root(start: Path | str | None = None) -> Path | None:
    """Walk up from ``start`` to the directory that contains ``.sprint/config.toml``."""
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / SPRINT_DIR / CONFIG_NAME).is_file():
            return candidate
    return None


def require_root(start: Path | str | None = None) -> Path:
    root = find_root(start)
    if root is None:
        raise SprintError(
            "not a sprintwarden project (no .sprint/config.toml here or in any parent)",
            hint="run `sprint init --ratchet-only` (or `sprint init`) at the repo root",
        )
    return root


_KNOWN: dict[str, set[str]] = {
    "project": {"name", "key", "mode", "stack"},
    "test": {
        "command",
        "command_windows",
        "reports",
        "timeout_minutes",
        "clean_reports_before_run",
        "env",
        "cwd",
        "sources",
        "suites",
    },
    "sprint": {"current", "id_pattern"},
    "gate": {
        "fail_on_new_skips",
        "fail_on_missing_tests",
        "require_current_sprint_tests",
        "fail_on_runner_error",
    },
    "hooks": {
        "claude_stop_hook",
        "claude_session_start",
        "claude_pretool_guard",
        "pretool_mode",
        "stop_hook_max_blocks",
        "git_pre_push",
    },
    "history": {"in_git", "keep"},
    "ui": {"allure_url"},
}
_SUITE_KEYS = {"name", "command", "command_windows", "reports", "cwd", "timeout_minutes", "env"}


def load_config(root: Path) -> Config:
    path = root / SPRINT_DIR / CONFIG_NAME
    text = read_text(path)
    if text is None:
        raise SprintError(f"{path} not found")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SprintError(f"{path}: invalid TOML ({exc})") from exc
    return config_from_dict(root, raw, source=str(path))


def config_from_dict(root: Path, raw: dict[str, Any], source: str = "config.toml") -> Config:
    warnings: list[str] = []
    for section, value in raw.items():
        if section not in _KNOWN:
            warnings.append(f"unknown section [{section}]")
            continue
        if not isinstance(value, dict):
            raise SprintError(f"{source}: [{section}] must be a table")
        for key in value:
            if key not in _KNOWN[section]:
                warnings.append(f"unknown key {section}.{key}")

    project = _table(raw, "project", source)
    test = _table(raw, "test", source)
    sprint = _table(raw, "sprint", source)
    gate = _table(raw, "gate", source)
    hooks = _table(raw, "hooks", source)
    history = _table(raw, "history", source)
    ui = _table(raw, "ui", source)

    name = _str(project, "name", root.name, source)
    key = _str(project, "key", "", source) or _default_key(name)
    mode = _str(project, "mode", "sprints", source)
    if mode not in MODES:
        raise SprintError(f"{source}: project.mode must be one of {', '.join(MODES)}, got {mode!r}")

    timeout = _num(test, "timeout_minutes", 30, source)
    suites: list[Suite] = []
    if "command" in test or "reports" in test:
        suites.append(
            Suite(
                name="default",
                command=_str(test, "command", "", source),
                command_windows=_str(test, "command_windows", "", source),
                reports=_str_list(test, "reports", source),
                cwd=_str(test, "cwd", "", source),
                timeout_minutes=timeout,
                env=_str_dict(test, "env", source),
            )
        )
    raw_suites = test.get("suites", [])
    if not isinstance(raw_suites, list):
        raise SprintError(f"{source}: test.suites must be an array of tables ([[test.suites]])")
    for i, s in enumerate(raw_suites):
        if not isinstance(s, dict):
            raise SprintError(f"{source}: test.suites[{i}] must be a table")
        for k in s:
            if k not in _SUITE_KEYS:
                warnings.append(f"unknown key test.suites[{i}].{k}")
        suites.append(
            Suite(
                name=_str(s, "name", f"suite{i + 1}", source),
                command=_str(s, "command", "", source),
                command_windows=_str(s, "command_windows", "", source),
                reports=_str_list(s, "reports", source),
                cwd=_str(s, "cwd", "", source),
                timeout_minutes=_num(s, "timeout_minutes", timeout, source),
                env=_str_dict(s, "env", source),
            )
        )
    if not suites:
        raise SprintError(
            f"{source}: no test command configured",
            hint="set [test] command and reports (see `sprint init --stack ...`)",
        )
    for s in suites:
        if not s.command.strip():
            raise SprintError(f"{source}: suite {s.name!r} has an empty command")
        if not s.reports:
            raise SprintError(f"{source}: suite {s.name!r} has no report globs (test.reports)")
        for g in s.reports:
            if os.path.isabs(g) or g.replace("\\", "/").split("/")[0] == "..":
                raise SprintError(f"{source}: report glob {g!r} must be relative to the repo root")

    id_pattern = _str(sprint, "id_pattern", DEFAULT_ID_PATTERN, source)
    try:
        rx = re.compile(id_pattern)
    except re.error as exc:
        raise SprintError(f"{source}: sprint.id_pattern is not a valid regex ({exc})") from exc
    if rx.groups < 1:
        raise SprintError(
            f"{source}: sprint.id_pattern needs a capture group for the sprint number"
        )

    current = _str(sprint, "current", "", source)
    if current:
        current = normalize_sprint_id(current)

    pretool_mode = _str(hooks, "pretool_mode", "warn", source)
    if pretool_mode not in ("warn", "block"):
        raise SprintError(f"{source}: hooks.pretool_mode must be 'warn' or 'block'")

    return Config(
        root=root,
        raw=raw,
        name=name,
        key=key,
        mode=mode,
        stack=_str(project, "stack", "custom", source),
        suites=suites,
        clean_reports_before_run=_bool(test, "clean_reports_before_run", True, source),
        sources=_str_list(test, "sources", source) if "sources" in test else [],
        sprint_current=current,
        id_pattern=id_pattern,
        fail_on_new_skips=_bool(gate, "fail_on_new_skips", True, source),
        fail_on_missing_tests=_bool(gate, "fail_on_missing_tests", True, source),
        require_current_sprint_tests=_bool(gate, "require_current_sprint_tests", True, source),
        fail_on_runner_error=_bool(gate, "fail_on_runner_error", True, source),
        claude_stop_hook=_bool(hooks, "claude_stop_hook", True, source),
        claude_session_start=_bool(hooks, "claude_session_start", True, source),
        claude_pretool_guard=_bool(hooks, "claude_pretool_guard", False, source),
        pretool_mode=pretool_mode,
        stop_hook_max_blocks=int(_num(hooks, "stop_hook_max_blocks", 3, source)),
        git_pre_push=_bool(hooks, "git_pre_push", True, source),
        history_in_git=_bool(history, "in_git", True, source),
        history_keep=int(_num(history, "keep", 0, source)),
        allure_url=_str(ui, "allure_url", "", source),
        warnings=warnings,
    )


def set_value(root: Path, section: str, key: str, value: Any) -> None:
    """Edit one value in config.toml in place, keeping comments and layout."""
    path = root / SPRINT_DIR / CONFIG_NAME
    text = read_text(path) or ""
    write_text(path, toml_set(text, section, key, value))


def _default_key(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return letters[:4] or "PROJ"


def _table(raw: dict[str, Any], name: str, source: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise SprintError(f"{source}: [{name}] must be a table")
    return value


def _str(t: dict[str, Any], key: str, default: str, source: str) -> str:
    value = t.get(key, default)
    if not isinstance(value, str):
        raise SprintError(f"{source}: {key} must be a string")
    return value


def _bool(t: dict[str, Any], key: str, default: bool, source: str) -> bool:
    value = t.get(key, default)
    if not isinstance(value, bool):
        raise SprintError(f"{source}: {key} must be true or false")
    return value


def _num(t: dict[str, Any], key: str, default: float, source: str) -> float:
    value = t.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise SprintError(f"{source}: {key} must be a non-negative number")
    return value


def _str_list(t: dict[str, Any], key: str, source: str) -> list[str]:
    value = t.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SprintError(f"{source}: {key} must be a list of strings")
    return list(value)


def _str_dict(t: dict[str, Any], key: str, source: str) -> dict[str, str]:
    value = t.get(key, {})
    if not isinstance(value, dict):
        raise SprintError(f"{source}: {key} must be a table of strings")
    return {str(k): str(v) for k, v in value.items()}
