"""Machine details out of the records the gate writes (D-033).

Run records are committed, often to public repos, and test output names the
machine it ran on all the time: the project's folder in a stack trace, a temp
folder in an assertion, the login in ``pytest-of-<login>``. Before a record is
written, every string in it except test and run IDs is rewritten:

- a path in the project: relative to the project's root (the root itself: ``.``)
- another path in the home folder: ``~/...``
- a path in a temp folder: ``$TMPDIR/...``
- a folder name a tool made from a path (``-Users-ada-proj``, as Claude Code names
  its folders): ``<project>`` for the project, ``~`` for another folder in the home
- a path a test framework cut short with ``…`` or ``...``: as far as it goes
- the login and the host name inside a path: ``$USER`` and ``$HOST``

The terminal report is printed from the record before this, so it keeps the
full paths.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

KEEP = frozenset({"id"})  # test and run IDs: the baseline and other runs match on them
MIN_CUT = 8  # the shortest cut-short piece of a folder that is still rewritten
MIN_NAME = 3  # logins and host names shorter than this are left alone
MIN_NAME_CUT = 4  # ...and the shortest cut-short login that is still rewritten
WINDOWS = os.name == "nt"
FLAGS = re.IGNORECASE if WINDOWS else 0

ROOT, HOME, TEMP, ENC_ROOT, ENC_HOME = "root", "home", "temp", "enc_root", "enc_home"
_ORDER = {ROOT: 0, HOME: 1, TEMP: 2}
_CUT_AS = {ROOT: "<project>", HOME: "~", TEMP: "$TMPDIR", ENC_ROOT: "<project>", ENC_HOME: "~"}

_SEPS = "/\\"
_DELIM = frozenset(" \t\r\n'\"`()<>[]{},;|=")  # what ends a path in running text
_CUT = re.compile(r"…|\.\.\.")  # how test frameworks mark a string they cut short
_BEFORE = r"(?<![A-Za-z0-9_.\-/\\~$])"  # a path starts here, not inside a longer one
_AFTER = r"(?![A-Za-z0-9_\-]|\.[A-Za-z0-9_\-])"  # ...and ends here (a full stop may follow)
_URL = r"(?:file://(?:/(?=[A-Za-z]:))?)?"  # file:///home/... and file:///C:/...
_TOKEN = re.compile(r"[^\s'\"`()<>\[\]{},;|]+")


def encode(path: str) -> str:
    """The folder name tools such as Claude Code make from a path."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def spellings(path: str) -> set[str]:
    """How a folder shows up in test output: as given and resolved, with and without
    macOS's /private, and on Windows with either slash (and doubled backslashes, as
    Python's repr writes them). Never the filesystem root or a drive."""
    found: set[str] = set()
    for p in {path, os.path.realpath(path)}:
        p = p.rstrip(_SEPS)
        if len(p) < 4:
            continue
        found.add(p)
        if p.startswith("/private/"):
            found.add(p[len("/private") :])
        elif p.startswith(("/var/", "/tmp/")) or p in ("/tmp", "/var/tmp"):
            found.add("/private" + p)
    if WINDOWS:
        for p in list(found):
            found |= {p.replace("\\", "/"), p.replace("\\", "\\\\")}
    return found


def _same(a: str, b: str) -> bool:
    return a.lower() == b.lower() if WINDOWS else a == b


class Redactor:
    """Rewrites the strings of a record for the project at ``root``."""

    def __init__(
        self,
        root: Path | str,
        *,
        homes: Iterable[str],
        temps: Iterable[str],
        logins: Iterable[str],
        hosts: Iterable[str],
    ) -> None:
        roots = spellings(str(root))
        home_set = {s for h in homes if h for s in spellings(h)}
        temp_set = {s for t in temps if t for s in spellings(t)}
        for r in list(roots):  # the project in its ~/ form, when it's in the home folder
            for h in home_set:
                if len(r) > len(h) and _same(r[: len(h)], h) and r[len(h)] in _SEPS:
                    rest = r[len(h) :]
                    roots |= {"~" + rest, "~" + rest.replace("\\", "/")}
        folders = [(s, ROOT) for s in roots] + [(s, HOME) for s in home_set]
        folders += [(s, TEMP) for s in temp_set]
        folders.sort(key=lambda f: (-len(f[0]), _ORDER[f[1]]))
        self._folders = folders  # whole folders, longest first
        self._paths = [
            (
                re.compile(_BEFORE + _URL + re.escape(s) + rf"(?:(?P<sep>[/\\])|{_AFTER})", FLAGS),
                kind,
            )
            for s, kind in folders
        ]

        encoded = {
            (encode(s), ENC_ROOT) for s, kind in folders if kind == ROOT and not s.startswith("~")
        }
        encoded |= {(encode(s), ENC_HOME) for s, kind in folders if kind == HOME}
        encoded = {(e, kind) for e, kind in encoded if len(e) >= MIN_CUT}
        self._encoded = sorted(encoded, key=lambda e: (-len(e[0]), e[1] != ENC_ROOT))
        self._encoded_rx = [
            (
                re.compile(r"(?<![A-Za-z0-9])" + re.escape(e) + r"[A-Za-z0-9\-]*", FLAGS),
                _CUT_AS[kind],
            )
            for e, kind in self._encoded
        ]

        users = {n for n in logins if n and len(n) >= MIN_NAME}
        # A host name often contains the login (ada-mbp), so hosts go first; a host
        # name that *is* the login (some Macs) is written $USER.
        machines = {h for h in hosts if h and len(h) >= MIN_NAME}
        machines = {h for h in machines if not any(_same(h, u) for u in users)}
        self._names: list[tuple[re.Pattern[str], str]] = []
        for names, place in ((machines, "$HOST"), (users, "$USER")):
            for n in sorted(names, key=len, reverse=True):
                self._names.append(
                    (re.compile(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", FLAGS), place)
                )
                if place == "$USER" and len(n) > MIN_NAME_CUT:
                    cut = "|".join(
                        re.escape(n[:k]) for k in range(len(n) - 1, MIN_NAME_CUT - 1, -1)
                    )
                    self._names.append(
                        (re.compile(rf"(?<![A-Za-z0-9])(?:{cut})(?=…|\.\.\.)", FLAGS), place)
                    )

    # ------------------------------------------------------------------ strings

    def text(self, s: str) -> str:
        if not s:
            return s
        for rx, kind in self._paths:
            s = rx.sub(self._whole(kind), s)
        for rx, place in self._encoded_rx:
            s = rx.sub(place, s)
        if "…" in s or "..." in s:
            s = self._cuts(s)
        return _TOKEN.sub(self._in_path, s) if self._names else s

    def value(self, v: Any) -> Any:
        """``v`` with every string rewritten; values under ``id`` keys are kept."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {k: (x if k in KEEP else self.value(x)) for k, x in v.items()}
        return v

    # ------------------------------------------------------------------ the parts

    @staticmethod
    def _whole(kind: str) -> Callable[[re.Match[str]], str]:
        def place(m: re.Match[str]) -> str:
            sep = m.group("sep") or ""
            if kind == ROOT:
                return "" if sep else "."
            return ("~" if kind == HOME else "$TMPDIR") + sep

        return place

    def _cuts(self, s: str) -> str:
        """Folders a test framework cut short: the end of one before ``…`` (written as
        its placeholder), the start of one after it (dropped)."""
        edits: list[tuple[int, int, str]] = []
        floor = 0
        for m in _CUT.finditer(s):
            a, b = m.span()
            if a < floor:
                continue
            start = a
            while start > floor and s[start - 1] not in _DELIM:
                start -= 1
            hit = self._prefix(s[start:a])
            if hit is not None:
                edits.append((start + hit[0], a, hit[1]))
            end = b
            while end < len(s) and s[end] not in _DELIM:
                end += 1
            j = self._suffix(s[b:end])
            if j:
                edits.append((a, b + j, "…"))
            floor = b + j
        for a, b, place in reversed(edits):
            s = s[:a] + place + s[b:]
        return s

    def _prefix(self, head: str) -> tuple[int, str] | None:
        """Where in ``head`` a cut-short folder starts, and what it becomes: the
        longest piece that starts a folder; the most general folder it starts."""
        starts = {0} | {j for j, c in enumerate(head) if c in _SEPS}
        starts |= {j + 1 for j, c in enumerate(head) if c in _SEPS}
        for k in sorted(starts):
            piece = head[k:]
            if len(piece) < MIN_CUT:
                break
            best: tuple[str, str] | None = None
            for lit, kind in self._folders + self._encoded:
                starts_it = len(lit) > len(piece) and _same(lit[: len(piece)], piece)
                if starts_it and (best is None or len(lit) < len(best[0])):
                    best = (lit, kind)
            if best:
                return k, _CUT_AS[best[1]]
        return None

    def _suffix(self, tail: str) -> int:
        """How much of ``tail`` ends a folder (up to a separator), or 0."""
        stops = sorted({j for j, c in enumerate(tail) if c in _SEPS} | {len(tail)}, reverse=True)
        for j in stops:
            piece = tail[:j]
            if len(piece) < MIN_CUT:
                break
            for lit, _ in self._folders:
                if len(lit) > len(piece) and _same(lit[-len(piece) :], piece):
                    return j
        return 0

    def _in_path(self, m: re.Match[str]) -> str:
        """The login and host name, but only inside something path-like, so a login
        that is also a word (``runner``) stays a word in a sentence."""
        tok = m.group(0)
        if not (any(c in tok for c in "/\\@") or tok.startswith("-") or "…" in tok or "..." in tok):
            return tok
        for rx, place in self._names:
            tok = rx.sub(place, tok)
        return tok


# ---------------------------------------------------------------------- this machine


def _homes() -> set[str]:
    found = {str(Path.home())}
    found |= {os.environ[k] for k in ("HOME", "USERPROFILE") if os.environ.get(k)}
    if not WINDOWS:  # the account's own home, even when HOME points elsewhere
        try:
            import pwd

            found.add(pwd.getpwuid(os.getuid()).pw_dir)
        except (ImportError, KeyError, OSError):
            pass
    return found


def _temps() -> set[str]:
    found = {tempfile.gettempdir(), "/tmp", "/var/tmp"}
    return found | {os.environ[k] for k in ("TMPDIR", "TEMP", "TMP") if os.environ.get(k)}


def _logins() -> set[str]:
    found = {os.environ[k] for k in ("USER", "LOGNAME", "USERNAME") if os.environ.get(k)}
    try:
        found.add(getpass.getuser())
    except (ImportError, KeyError, OSError):
        pass
    if not WINDOWS:
        try:
            import pwd

            found.add(pwd.getpwuid(os.getuid()).pw_name)
        except (ImportError, KeyError, OSError):
            pass
    return found


def _hosts() -> set[str]:
    try:
        host = socket.gethostname()
    except OSError:
        return set()
    return {h for h in (host, host.split(".")[0]) if h.lower() != "localhost"}


def for_root(root: Path | str) -> Redactor:
    """A redactor for the project at ``root`` on this machine."""
    return Redactor(root, homes=_homes(), temps=_temps(), logins=_logins(), hosts=_hosts())
