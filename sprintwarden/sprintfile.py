"""Sprint files: Markdown with TOML front matter between ``+++`` lines.

The front matter holds the machine-readable part (status, goal, acceptance
criteria); the Markdown body is free text, including the "Notes / decisions"
log that agents append to.
"""

from __future__ import annotations

import datetime as dt
import re
import string
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from sprintwarden.attribution import TestMatcher, format_sprint_id, normalize_sprint_id
from sprintwarden.util import SprintError, read_text, slugify, toml_literal, trailing_comment

STATUSES = ("planned", "active", "closed", "parked")
# Sprints that are not being worked on yet (or any more) may list ACs without tests.
UNSTARTED = ("planned", "parked")
NOTES_HEADING = "## Notes / decisions"
_FENCE = "+++"


@dataclass
class AC:
    id: str
    desc: str
    tests: list[str]


@dataclass
class Sprint:
    id: str
    title: str
    status: str
    goal: str
    started: str
    closed: str
    acs: list[AC]
    out_of_scope: list[str]
    path: Path
    body: str
    extra: dict[str, Any] = field(default_factory=dict)
    parked: str = ""
    parked_reason: str = ""

    @property
    def number(self) -> int:
        return int(self.id[1:])

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "goal": self.goal,
            "started": self.started,
            "closed": self.closed,
            "parked": self.parked,
            "parked_reason": self.parked_reason,
            "acs": [{"id": a.id, "desc": a.desc, "tests": a.tests} for a in self.acs],
            "out_of_scope": self.out_of_scope,
            "file": self.path.name,
            "notes": notes(self.body),
            "body": self.body,
        }


def split_front_matter(text: str, source: str = "sprint file") -> tuple[str, str]:
    text = text.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        raise SprintError(f"{source}: must start with a '+++' line (TOML front matter)")
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    raise SprintError(f"{source}: front matter is not closed with a '+++' line")


def _date_str(value: Any, key: str, source: str) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    raise SprintError(f"{source}: {key} must be a date like 2026-10-06")


def parse_sprint_text(text: str, path: Path) -> Sprint:
    source = str(path)
    front, body = split_front_matter(text, source)
    try:
        data = tomllib.loads(front)
    except tomllib.TOMLDecodeError as exc:
        raise SprintError(f"{source}: invalid TOML front matter ({exc})") from exc

    if "id" not in data:
        raise SprintError(f'{source}: front matter needs id = "S01"')
    sprint_id = normalize_sprint_id(str(data["id"]))
    status = str(data.get("status", "planned")).strip().lower()
    if status not in STATUSES:
        raise SprintError(f"{source}: status must be one of {', '.join(STATUSES)}, got {status!r}")

    out_of_scope = _str_list(data.get("out_of_scope", []), "out_of_scope", source)
    acs: list[AC] = []
    seen: set[str] = set()
    raw_acs = data.get("ac", [])
    if not isinstance(raw_acs, list):
        raise SprintError(f"{source}: acceptance criteria must be [[ac]] tables")
    for i, raw in enumerate(raw_acs):
        if not isinstance(raw, dict):
            raise SprintError(f"{source}: [[ac]] #{i + 1} must be a table")
        ac_id = str(raw.get("id", f"AC{i + 1}")).strip()
        if ac_id in seen:
            raise SprintError(f"{source}: duplicate AC id {ac_id}")
        seen.add(ac_id)
        tests = _str_list(raw.get("tests", []), f"{ac_id}.tests", source)
        for pattern in tests:
            TestMatcher(pattern)  # validate early, with a clear error
        # `out_of_scope` written after the [[ac]] tables lands in the last AC in
        # TOML. Treat it as the sprint-level key it was meant to be.
        if "out_of_scope" in raw:
            out_of_scope += _str_list(raw["out_of_scope"], "out_of_scope", source)
        acs.append(AC(id=ac_id, desc=str(raw.get("desc", "")).strip(), tests=tests))

    known = {
        "id",
        "title",
        "status",
        "goal",
        "started",
        "closed",
        "parked",
        "parked_reason",
        "ac",
        "out_of_scope",
    }
    return Sprint(
        id=sprint_id,
        title=str(data.get("title", "")).strip(),
        status=status,
        goal=str(data.get("goal", "")).strip(),
        started=_date_str(data.get("started"), "started", source),
        closed=_date_str(data.get("closed"), "closed", source),
        acs=acs,
        out_of_scope=out_of_scope,
        path=path,
        body=body,
        extra={k: v for k, v in data.items() if k not in known},
        parked=_date_str(data.get("parked"), "parked", source),
        parked_reason=str(data.get("parked_reason", "")).strip(),
    )


def _str_list(value: Any, key: str, source: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SprintError(f"{source}: {key} must be a list of strings")
    return list(value)


def load_sprint(path: Path) -> Sprint:
    text = read_text(path)
    if text is None:
        raise SprintError(f"{path} not found")
    return parse_sprint_text(text, path)


def sprint_files(sprints_dir: Path) -> list[Path]:
    if not sprints_dir.is_dir():
        return []
    return sorted(p for p in sprints_dir.glob("*.md") if not p.name.startswith("."))


def load_sprints(sprints_dir: Path, *, strict: bool = True) -> tuple[list[Sprint], list[str]]:
    """Load every sprint file, sorted by number. Returns (sprints, errors)."""
    sprints: list[Sprint] = []
    errors: list[str] = []
    for path in sprint_files(sprints_dir):
        try:
            sprints.append(load_sprint(path))
        except SprintError as exc:
            if strict:
                raise
            errors.append(str(exc))
    sprints.sort(key=lambda s: s.number)
    return sprints, errors


def validate_sprints(sprints: list[Sprint], current: str) -> list[str]:
    problems: list[str] = []
    ids: dict[str, Path] = {}
    for s in sprints:
        if s.id in ids:
            problems.append(f"sprint {s.id} is defined twice ({ids[s.id].name}, {s.path.name})")
        ids[s.id] = s.path
        prefix = s.path.name.split("-", 1)[0].split(".", 1)[0]
        try:
            if normalize_sprint_id(prefix) != s.id:
                problems.append(f"{s.path.name}: file name does not start with {s.id}")
        except SprintError:
            problems.append(
                f"{s.path.name}: file name should start with the sprint id ({s.id}-...)"
            )
        if s.status == "active" and not s.started:
            problems.append(f"{s.path.name}: active sprint has no 'started' date")
        if s.status == "closed" and not s.closed:
            problems.append(f"{s.path.name}: closed sprint has no 'closed' date")
        for ac in s.acs:
            if not ac.tests and s.status not in UNSTARTED:
                problems.append(f"{s.id} {ac.id}: no tests listed, so it can never be satisfied")
    active = [s for s in sprints if s.status == "active"]
    if len(active) > 1:
        problems.append("more than one active sprint: " + ", ".join(s.id for s in active))
    if active and current and active[0].id != current:
        problems.append(f"active sprint is {active[0].id} but config sprint.current is {current}")
    if active and not current:
        problems.append(f"sprint {active[0].id} is active but config sprint.current is empty")
    if current and not active:
        if current not in ids:
            problems.append(f"config sprint.current is {current}, but no such sprint file exists")
        else:
            problems.append(f"config sprint.current is {current}, but that sprint is not active")
    return problems


def find_sprint(sprints: list[Sprint], sprint_id: str) -> Sprint | None:
    sid = normalize_sprint_id(sprint_id)
    return next((s for s in sprints if s.id == sid), None)


def active_sprint(sprints: list[Sprint]) -> Sprint | None:
    return next((s for s in sprints if s.status == "active"), None)


def next_sprint_id(sprints: list[Sprint]) -> str:
    return format_sprint_id(max((s.number for s in sprints), default=0) + 1)


def sprint_filename(sprint_id: str, title: str) -> str:
    return f"{sprint_id}-{slugify(title)}.md"


def render_sprint(
    sprint_id: str,
    title: str,
    *,
    goal: str = "",
    status: str = "planned",
    started: str = "",
    example: str = "",
) -> str:
    """Render ``templates/sprint.md`` for a new sprint."""
    template = resources.files("sprintwarden").joinpath("templates", "sprint.md")
    text = string.Template(template.read_text(encoding="utf-8"))
    return text.substitute(
        id=toml_literal(sprint_id),
        sid=sprint_id,
        title=toml_literal(title),
        status=toml_literal(status),
        goal=toml_literal(goal),
        started=started if started else '""',
        example=f"`{example or sprint_id + '_doesThing'}`",
    )


_KEY_LINE = r"^(?P<lead>\s*{key}\s*=\s*)(?P<value>.*)$"


def set_fields(text: str, **fields: Any) -> str:
    """Update top-level front-matter keys in place (before the first [[ac]] table)."""
    front, body = split_front_matter(text)
    lines = front.splitlines(keepends=True)
    top_end = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
    for key, value in fields.items():
        literal = value if isinstance(value, _Raw) else toml_literal(value)
        rx = re.compile(_KEY_LINE.format(key=re.escape(key)))
        for i in range(top_end):
            m = rx.match(lines[i].rstrip("\r\n"))
            if m:
                comment = trailing_comment(m.group("value"))
                lines[i] = f"{m.group('lead')}{literal}{comment}\n"
                break
        else:
            lines.insert(top_end, f"{key} = {literal}\n")
            top_end += 1
    return f"{_FENCE}\n{''.join(lines)}{_FENCE}\n{body}"


class _Raw(str):
    """A pre-rendered TOML literal (e.g. a bare date)."""


def raw_literal(text: str) -> _Raw:
    return _Raw(text)


def append_note(text: str, note: str, *, date: str, agent: str) -> str:
    """Append ``- <date>: <note> (agent: <agent>)`` under "Notes / decisions"."""
    entry = f"- {date}: {' '.join(note.split())} (agent: {agent})\n"
    front_and_fence, body = _split_keep(text)
    lines = body.splitlines(keepends=True)
    head = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == NOTES_HEADING.lower()), None
    )
    if head is None:
        if body and not body.endswith("\n"):
            body += "\n"
        sep = "" if body.endswith("\n\n") or not body else "\n"
        return f"{front_and_fence}{body}{sep}{NOTES_HEADING}\n{entry}"
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    # Insert after the last non-blank line of the section.
    pos = end
    while pos > head + 1 and not lines[pos - 1].strip():
        pos -= 1
    if pos > 0 and not lines[pos - 1].endswith("\n"):
        lines[pos - 1] += "\n"
    lines.insert(pos, entry)
    return front_and_fence + "".join(lines)


def _split_keep(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            return "".join(lines[: i + 1]), "".join(lines[i + 1 :])
    raise SprintError("sprint file has no closed front matter")


def notes(body: str) -> list[str]:
    lines = body.splitlines()
    head = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == NOTES_HEADING.lower()), None
    )
    if head is None:
        return []
    out: list[str] = []
    for line in lines[head + 1 :]:
        if line.startswith("## "):
            break
        if line.strip().startswith("- "):
            out.append(line.strip()[2:])
    return out
