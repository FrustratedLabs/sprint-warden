"""The global project registry, ``~/.sprintwarden/registry.toml``.

    [[project]]
    path = "~/code/billing-service"

Only paths are stored; each project's state is read from its own ``.sprint/``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from sprintwarden.stacks import global_home
from sprintwarden.util import SprintError, read_text, toml_literal, write_text


def registry_path() -> Path:
    return global_home() / "registry.toml"


def _display(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).resolve()


def load() -> list[Path]:
    text = read_text(registry_path())
    if not text:
        return []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SprintError(f"{registry_path()}: invalid TOML ({exc})") from exc
    out: list[Path] = []
    for entry in data.get("project", []):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            p = _resolve(entry["path"])
            if p not in out:
                out.append(p)
    return out


def save(paths: list[Path]) -> None:
    lines = ["# Projects shown by `sprint ui`. Managed by `sprint register` / `sprint unregister`.\n"]
    for p in paths:
        lines.append(f"\n[[project]]\npath = {toml_literal(_display(p))}\n")
    write_text(registry_path(), "".join(lines))


def register(path: Path) -> bool:
    path = path.resolve()
    current = load()
    if path in current:
        return False
    current.append(path)
    save(current)
    return True


def unregister(path: Path) -> bool:
    path = path.resolve()
    current = load()
    if path not in current:
        return False
    save([p for p in current if p != path])
    return True
