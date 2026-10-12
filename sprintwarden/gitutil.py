"""Thin wrappers around the ``git`` CLI. Every function degrades gracefully
outside a git repository (returns None/False) so the ratchet works anywhere."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from sprintwarden.util import SprintError

# Files the gate itself writes. They never make the tree "dirty" for clean-HEAD
# checks and never count as "something changed" for the Stop hook.
STATE_EXCLUDES = (".sprint/runs", ".sprint/latest.json", ".sprint/out")


def git(root: Path, *args: str, check: bool = False, input: str | None = None) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input,
            stdin=None if input is not None else subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        if check:
            raise SprintError("git is not installed or not on PATH") from exc
        return subprocess.CompletedProcess(["git", *args], 127, "", "git not found")
    if check and proc.returncode != 0:
        raise SprintError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def toplevel(path: Path) -> Path | None:
    proc = git(path, "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def is_repo(root: Path) -> bool:
    return toplevel(root) is not None


def head(root: Path) -> str | None:
    proc = git(root, "rev-parse", "--verify", "-q", "HEAD")
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def branch(root: Path) -> str | None:
    for var in ("GITHUB_HEAD_REF", "CI_COMMIT_REF_NAME", "BUILDKITE_BRANCH", "BRANCH_NAME"):
        if os.environ.get(var):
            return os.environ[var]
    proc = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        proc = git(root, "symbolic-ref", "--short", "-q", "HEAD")  # repo without commits
    name = proc.stdout.strip()
    return name or None


def _pathspec(exclude_state: bool) -> list[str]:
    spec = ["--", "."]
    if exclude_state:
        spec += [f":(exclude){p}" for p in STATE_EXCLUDES]
    return spec


def status_entries(root: Path, *, exclude_state: bool = True) -> list[tuple[str, str]] | None:
    """``[(XY, path)]`` from ``git status --porcelain``, paths relative to the repo top."""
    proc = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", *_pathspec(exclude_state))
    if proc.returncode != 0:
        return None
    entries: list[tuple[str, str]] = []
    parts = proc.stdout.split("\0")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        xy, path = item[:2], item[3:]
        entries.append((xy, path))
        if xy[0] in "RC":
            i += 1  # skip the rename source
    return entries


def is_dirty(root: Path) -> bool | None:
    entries = status_entries(root)
    return None if entries is None else bool(entries)


def fingerprint(root: Path) -> str | None:
    """Identify the exact working-tree state: HEAD + changed paths + their sizes/mtimes.

    ``git status --porcelain`` alone is not enough: editing an already-modified
    file a second time doesn't change its status line, and the Stop hook would
    wrongly skip the gate.
    """
    top = toplevel(root)
    if top is None:
        return None
    entries = status_entries(root)
    if entries is None:
        return None
    h = hashlib.sha256()
    h.update((head(root) or "no-head").encode())
    for xy, path in sorted(entries, key=lambda e: e[1]):
        h.update(f"\0{xy}\0{path}".encode())
        try:
            st = os.stat(top / path)
            h.update(f"\0{st.st_size}\0{st.st_mtime_ns}".encode())
        except OSError:
            h.update(b"\0gone")
    return h.hexdigest()[:20]


def info(root: Path) -> dict:
    """The ``git`` block of a run record."""
    if not is_repo(root):
        return {"head": None, "branch": None, "dirty": None, "fingerprint": None}
    return {
        "head": head(root),
        "branch": branch(root),
        "dirty": is_dirty(root),
        "fingerprint": fingerprint(root),
    }


def show_file(root: Path, ref: str, relpath: str) -> str | None:
    """Content of ``relpath`` (relative to ``root``) at ``ref``, or None."""
    proc = git(root, "show", f"{ref}:./{relpath}")
    return proc.stdout if proc.returncode == 0 else None


def tag_exists(root: Path, name: str) -> bool:
    return git(root, "rev-parse", "-q", "--verify", f"refs/tags/{name}").returncode == 0


def create_tag(root: Path, name: str, message: str) -> None:
    git(root, "tag", "-a", name, "-m", message, check=True)


def commit_paths(root: Path, paths: list[str], message: str) -> str | None:
    """Stage ``paths`` and commit them. Returns the new HEAD, or None if nothing changed."""
    existing = [p for p in paths if (root / p).exists()]
    git(root, "add", "--all", "--", *existing, check=True)
    staged = git(root, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return None
    git(root, "commit", "-q", "-m", message, check=True)
    return head(root)


def hooks_dir(root: Path) -> Path | None:
    proc = git(root, "rev-parse", "--git-path", "hooks")
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (root / path).resolve()


def hooks_path_config(root: Path) -> str | None:
    proc = git(root, "config", "--get", "core.hooksPath")
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def path_key(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def tracked_files(root: Path, files: list[Path]) -> set[str]:
    """The subset of ``files`` tracked by git, as :func:`path_key` strings."""
    top = toplevel(root)
    if top is None:
        return set()
    tracked: set[str] = set()
    for i in range(0, len(files), 200):  # stay well under Windows' command-line limit
        chunk = [str(p) for p in files[i : i + 200]]
        proc = git(root, "ls-files", "-z", "--full-name", "--", *chunk)
        if proc.returncode != 0:
            continue
        tracked.update(path_key(top / rel) for rel in proc.stdout.split("\0") if rel)
    return tracked
