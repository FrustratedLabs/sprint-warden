"""Small shared helpers: errors, time, atomic file writes, TOML literals."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_GATE_FAIL = 1
EXIT_USAGE = 2


class SprintError(Exception):
    """A configuration or usage error. The CLI turns it into exit code 2."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def iso(ts: dt.datetime | None = None) -> str:
    """UTC timestamp like ``2026-10-12T10:31:05Z``."""
    ts = ts or utcnow()
    return ts.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(ts: dt.datetime | None = None) -> str:
    """UTC timestamp with milliseconds, for ordering events within one second."""
    ts = ts or dt.datetime.now(dt.timezone.utc)
    ts = ts.astimezone(dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def today() -> str:
    return dt.date.today().isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + rename).

    Readers such as the dashboard never see a half-written file. On Windows the
    rename can fail briefly while another process has the target open, so retry.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o666 & ~_umask()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def dumps_json(data: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, dumps_json(data))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SprintError(f"{path}: invalid JSON ({exc})") from exc


def read_text(path: Path, default: str | None = None) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def write_text(path: Path, text: str) -> None:
    atomic_write_text(path, text)


def slugify(title: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "sprint"


def toml_literal(value: Any) -> str:
    """Render a Python value as a TOML literal (strings, bools, numbers, lists)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ " + ", ".join(f"{_toml_key(k)} = {toml_literal(v)}" for k, v in value.items()) + " }"
        )
    text = str(value)
    if "\\" in text and "'" not in text and "\n" not in text:
        return f"'{text}'"  # literal string keeps regexes readable
    escaped = (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else toml_literal(key)


_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def toml_set(text: str, section: str, key: str, value: Any) -> str:
    """Set ``key = value`` inside ``[section]`` of a TOML document, keeping comments.

    tomllib can only read, and the files we edit are human-maintained, so we
    edit the one line in place instead of re-serialising the whole document.
    """
    lines = text.splitlines(keepends=True)
    literal = toml_literal(value)
    key_re = re.compile(rf"^(\s*){re.escape(key)}(\s*=\s*)(.*)$")
    in_section = section == ""
    section_start = 0 if in_section else None
    insert_at = None
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if m and not line.lstrip().startswith("#"):
            if in_section:
                insert_at = i
                break
            if m.group(1) == section and not line.lstrip().startswith("[["):
                in_section = True
                section_start = i + 1
            continue
        if in_section:
            km = key_re.match(line.rstrip("\r\n"))
            if km:
                comment = trailing_comment(km.group(3))
                eol = "\n" if line.endswith("\n") else ""
                lines[i] = f"{km.group(1)}{key}{km.group(2)}{literal}{comment}{eol}"
                return "".join(lines)
    if section_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"\n[{section}]\n{key} = {literal}\n")
        return "".join(lines)
    if insert_at is None:
        insert_at = len(lines)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
    # Insert right after the last non-blank line of the section.
    pos = insert_at
    while pos > section_start and not lines[pos - 1].strip():
        pos -= 1
    lines.insert(pos, f"{key} = {literal}\n")
    return "".join(lines)


def trailing_comment(value_part: str) -> str:
    """Return the ``  # comment`` suffix of a TOML value, if any (string-aware)."""
    quote = None
    i = 0
    while i < len(value_part):
        ch = value_part[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == "#":
            j = i
            while j > 0 and value_part[j - 1] in " \t":
                j -= 1
            return value_part[j:]
        i += 1
    return ""


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"
