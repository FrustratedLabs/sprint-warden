"""Report-glob matching relative to the repo root.

``**`` matches any number of directories. While expanding ``**`` we skip
directories that never hold test reports but can be enormous (``.git``,
``node_modules``, virtualenvs), which keeps globs like
``**/build/test-results/**/*.xml`` fast in big monorepos. Spelling such a
directory out explicitly (``node_modules/x/*.xml``) still works.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

PRUNE = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".gradle",
        ".m2",
        ".cache",
        ".next",
        ".nuxt",
        ".turbo",
        "bower_components",
        ".terraform",
    }
)
_MAGIC = set("*?[")


def _has_magic(segment: str) -> bool:
    return any(ch in _MAGIC for ch in segment)


def _match(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch(name, pattern) if os.name == "nt" else fnmatch.fnmatchcase(name, pattern)


def _walk(base: Path, segments: list[str]) -> Iterator[Path]:
    if not segments:
        if base.is_file():
            yield base
        return
    head, rest = segments[0], segments[1:]
    if head == "**":
        yield from _walk(base, rest)
        try:
            entries = list(os.scandir(base))
        except OSError:
            return
        for entry in entries:
            if entry.name in PRUNE:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    yield from _walk(Path(entry.path), segments)
            except OSError:
                continue
        return
    if not _has_magic(head):
        nxt = base / head
        if rest:
            if nxt.is_dir():
                yield from _walk(nxt, rest)
        elif nxt.is_file():
            yield nxt
        return
    try:
        entries = list(os.scandir(base))
    except OSError:
        return
    for entry in entries:
        if not _match(entry.name, head):
            continue
        try:
            if rest:
                if entry.is_dir():
                    yield from _walk(Path(entry.path), rest)
            elif entry.is_file():
                yield Path(entry.path)
        except OSError:
            continue


def find_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    """All files under ``root`` matching any pattern, deduplicated and sorted."""
    seen: dict[str, Path] = {}
    for pattern in patterns:
        segments = [s for s in pattern.replace("\\", "/").split("/") if s not in ("", ".")]
        # Collapse runs of ** so a/**/**/b doesn't explode combinatorially.
        collapsed: list[str] = []
        for s in segments:
            if not (s == "**" and collapsed and collapsed[-1] == "**"):
                collapsed.append(s)
        for path in _walk(root, collapsed):
            seen.setdefault(os.path.normcase(str(path)), path)
    return sorted(seen.values(), key=lambda p: str(p))


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
