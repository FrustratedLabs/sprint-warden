"""Stack templates (``templates/stacks/*.toml``) and auto-detection.

Adding a stack only needs a new template file; see docs/ADDING_A_STACK.md.
Users can also drop their own templates into ``~/.sprintwarden/stacks/``.
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from sprintwarden.util import SprintError


@dataclass
class DetectRule:
    file: str
    contains: str = ""


@dataclass
class Stack:
    name: str
    label: str
    priority: int
    command: str
    reports: list[str]
    command_windows: str = ""
    sources: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    detect: list[DetectRule] = field(default_factory=list)
    example_test: str = "S01_doesThing"
    origin: str = ""


def global_home() -> Path:
    """``~/.sprintwarden`` (override with ``SPRINT_HOME``, used by the tests)."""
    override = os.environ.get("SPRINT_HOME")
    return Path(override).expanduser() if override else Path.home() / ".sprintwarden"


def _parse(text: str, origin: str) -> Stack:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SprintError(f"stack template {origin}: invalid TOML ({exc})") from exc
    test = data.get("test", {})
    try:
        return Stack(
            name=str(data["name"]),
            label=str(data.get("label", data["name"])),
            priority=int(data.get("priority", 10)),
            command=str(test.get("command", "")),
            command_windows=str(test.get("command_windows", "")),
            reports=list(test.get("reports", [])),
            sources=list(test.get("sources", [])),
            env={str(k): str(v) for k, v in test.get("env", {}).items()},
            detect=[
                DetectRule(str(r["file"]), str(r.get("contains", "")))
                for r in data.get("detect", [])
            ],
            example_test=str(data.get("example_test", "S01_doesThing")),
            origin=origin,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SprintError(f"stack template {origin}: {exc}") from exc


def load_stacks() -> dict[str, Stack]:
    stacks: dict[str, Stack] = {}
    folder = resources.files("sprintwarden").joinpath("templates", "stacks")
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml"):
            stack = _parse(entry.read_text(encoding="utf-8"), f"builtin:{entry.name}")
            stacks[stack.name] = stack
    user_dir = global_home() / "stacks"
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.toml")):
            stack = _parse(path.read_text(encoding="utf-8"), str(path))
            stacks[stack.name] = stack  # user templates override built-ins
    return stacks


def get_stack(name: str) -> Stack:
    stacks = load_stacks()
    if name not in stacks:
        raise SprintError(
            f"unknown stack {name!r}", hint="known stacks: " + ", ".join(sorted(stacks))
        )
    return stacks[name]


def _rule_matches(root: Path, rule: DetectRule) -> bool:
    try:
        names = [e.name for e in os.scandir(root) if e.is_file()]
    except OSError:
        return False
    for name in names:
        if not fnmatch.fnmatch(name, rule.file):
            continue
        if not rule.contains:
            return True
        try:
            with open(root / name, encoding="utf-8", errors="replace") as fh:
                if rule.contains in fh.read(512 * 1024):
                    return True
        except OSError:
            continue
    return False


def detect_stacks(root: Path) -> list[Stack]:
    """Stacks whose marker files exist at ``root``, best match first."""
    found = [
        s
        for s in load_stacks().values()
        if s.detect and any(_rule_matches(root, r) for r in s.detect)
    ]
    # jest and vitest both match package.json; prefer the more specific one.
    names = {s.name for s in found}
    if "vitest" in names and "jest" in names:
        pkg = (
            (root / "package.json").read_text(encoding="utf-8", errors="replace")
            if (root / "package.json").is_file()
            else ""
        )
        drop = "jest" if "vitest" in pkg else "vitest"
        found = [s for s in found if s.name != drop]
    found.sort(key=lambda s: (-s.priority, s.name))
    return found
