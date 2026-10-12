from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from sprintwarden.sprintfile import (
    active_sprint,
    append_note,
    find_sprint,
    load_sprints,
    next_sprint_id,
    notes,
    parse_sprint_text,
    raw_literal,
    render_sprint,
    set_fields,
    split_front_matter,
    sprint_filename,
    validate_sprints,
)
from sprintwarden.util import SprintError

SPEC_EXAMPLE = """+++
id     = "S03"
title  = "Reports"
status = "active"          # planned | active | closed
goal   = "User can export the monthly report as PDF"
started = 2026-10-06
closed  = ""

[[ac]]
id    = "AC1"
desc  = "Export button on dashboard produces a PDF"
tests = ["S03_exportsPdf"]                 # substring or /regex/ on full test name

[[ac]]
id    = "AC2"
desc  = "Empty month shows a placeholder page"
tests = ["/S03_.*Placeholder.*/"]

out_of_scope = ["scheduling", "email delivery"]
+++

## Notes / decisions
- 2026-10-07: chose server-side PDF rendering (agent: claude-code)
"""


def test_S01_parses_the_spec_example():
    s = parse_sprint_text(SPEC_EXAMPLE, Path("S03-reports.md"))
    assert s.id == "S03" and s.title == "Reports" and s.status == "active"
    assert s.goal == "User can export the monthly report as PDF"
    assert s.started == "2026-10-06" and s.closed == ""
    assert [(a.id, a.tests) for a in s.acs] == [
        ("AC1", ["S03_exportsPdf"]),
        ("AC2", ["/S03_.*Placeholder.*/"]),
    ]
    # In TOML this key lands inside the last [[ac]]; we hoist it to the sprint.
    assert s.out_of_scope == ["scheduling", "email delivery"]
    assert notes(s.body) == ["2026-10-07: chose server-side PDF rendering (agent: claude-code)"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter", "must start with"),
        ("+++\nid = 'S01'\n", "not closed"),
        ("+++\nid = \n+++\n", "invalid TOML"),
        ("+++\ntitle = 'x'\n+++\n", "needs id"),
        ("+++\nid = 'S01'\nstatus = 'done'\n+++\n", "status must be"),
        ("+++\nid = 'X1'\n+++\n", "invalid sprint id"),
        ("+++\nid = 'S01'\n[[ac]]\nid='AC1'\n[[ac]]\nid='AC1'\n+++\n", "duplicate AC"),
        ("+++\nid = 'S01'\n[[ac]]\nid='AC1'\ntests=['/(/']\n+++\n", "invalid AC test regex"),
        ("+++\nid = 'S01'\n[[ac]]\nid='AC1'\ntests=[1]\n+++\n", "list of strings"),
    ],
)
def test_S01_invalid_sprint_files_raise_clear_errors(text, message):
    with pytest.raises(SprintError, match=message):
        parse_sprint_text(text, Path("S01-x.md"))


def test_S01_front_matter_tolerates_bom_and_crlf():
    text = "﻿+++\r\nid = 'S1'\r\n+++\r\nbody\r\n"
    front, body = split_front_matter(text)
    assert "id" in front and body.strip() == "body"
    assert parse_sprint_text(text, Path("S01-a.md")).id == "S01"


def test_S01_rendered_template_round_trips():
    text = render_sprint("S04", 'Billing "v2"', goal="Invoices round to cents", status="planned")
    s = parse_sprint_text(text, Path("S04-billing-v2.md"))
    assert s.id == "S04" and s.title == 'Billing "v2"' and s.status == "planned"
    assert s.goal == "Invoices round to cents"
    assert s.started == "" and s.acs[0].id == "AC1" and s.acs[0].tests == []


def test_S01_set_fields_keeps_comments_and_handles_dates():
    text = set_fields(SPEC_EXAMPLE, status="closed", closed=raw_literal("2026-10-20"))
    s = parse_sprint_text(text, Path("S03-reports.md"))
    assert s.status == "closed" and s.closed == "2026-10-20"
    assert 'status = "closed"          # planned | active | closed' in text
    # AC tables are untouched
    assert s.acs[0].tests == ["S03_exportsPdf"]
    assert text.endswith(SPEC_EXAMPLE.split("+++", 2)[2])


def test_S01_set_fields_inserts_missing_key_before_tables():
    text = "+++\nid = 'S01'\n[[ac]]\nid = 'AC1'\n+++\nbody\n"
    out = set_fields(text, status="active")
    data = tomllib.loads(split_front_matter(out)[0])
    assert data["status"] == "active" and data["ac"][0]["id"] == "AC1"


def test_S01_set_fields_is_not_fooled_by_hash_in_string():
    text = '+++\nid = "S01"\ngoal = "Fix #12 bug"   # note\n+++\n'
    out = set_fields(text, goal="Fix #13 bug")
    assert 'goal = "Fix #13 bug"   # note' in out


def test_S01_append_note_to_existing_section():
    out = append_note(
        SPEC_EXAMPLE, "picked  weasyprint\n over wkhtml", date="2026-10-08", agent="codex"
    )
    assert notes(parse_sprint_text(out, Path("S03-r.md")).body) == [
        "2026-10-07: chose server-side PDF rendering (agent: claude-code)",
        "2026-10-08: picked weasyprint over wkhtml (agent: codex)",
    ]


def test_S01_append_note_before_following_section():
    text = "+++\nid='S01'\n+++\n## Notes / decisions\n- a\n\n## Later\ntext\n"
    out = append_note(text, "b", date="2026-01-01", agent="human")
    assert "- a\n- 2026-01-01: b (agent: human)\n\n## Later\ntext\n" in out


def test_S01_append_note_creates_section():
    text = "+++\nid='S01'\n+++\nSome plan text"
    out = append_note(text, "first", date="2026-01-01", agent="human")
    assert out.endswith(
        "Some plan text\n\n## Notes / decisions\n- 2026-01-01: first (agent: human)\n"
    )


def _write(dirpath: Path, name: str, sid: str, status: str, extra: str = "") -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    started = "started = 2026-01-01\n" if status != "planned" else ""
    closed = "closed = 2026-01-14\n" if status == "closed" else ""
    (dirpath / name).write_text(
        f"+++\nid = '{sid}'\nstatus = '{status}'\n{started}{closed}{extra}+++\n", encoding="utf-8"
    )


def test_S01_load_and_validate_sprints(tmp_path):
    d = tmp_path / "sprints"
    _write(d, "S01-auth.md", "S01", "closed")
    _write(d, "S10-later.md", "S10", "planned")
    _write(d, "S02-billing.md", "S02", "active")
    sprints, errors = load_sprints(d)
    assert [s.id for s in sprints] == ["S01", "S02", "S10"] and not errors
    assert validate_sprints(sprints, "S02") == []
    assert active_sprint(sprints).id == "S02"
    assert find_sprint(sprints, "s2").id == "S02"
    assert next_sprint_id(sprints) == "S11"
    assert sprint_filename("S11", "Big Refactor!") == "S11-big-refactor.md"


def test_S01_validate_reports_rule_violations(tmp_path):
    d = tmp_path / "sprints"
    _write(d, "S01-a.md", "S01", "active")
    _write(d, "S02-b.md", "S02", "active")
    _write(d, "S07-wrong-name.md", "S03", "planned")
    _write(d, "S04-c.md", "S04", "closed", extra="[[ac]]\nid='AC1'\n")
    sprints, _ = load_sprints(d)
    problems = "\n".join(validate_sprints(sprints, "S02"))
    assert "more than one active sprint" in problems
    assert "active sprint is S01 but config sprint.current is S02" in problems
    assert "S07-wrong-name.md: file name does not start with S03" in problems
    assert "S04 AC1: no tests listed" in problems


def test_S01_validate_current_without_active(tmp_path):
    d = tmp_path / "sprints"
    _write(d, "S01-a.md", "S01", "closed")
    sprints, _ = load_sprints(d)
    assert "not active" in validate_sprints(sprints, "S01")[0]
    assert "no such sprint file" in validate_sprints(sprints, "S09")[0]


def test_S01_non_strict_load_collects_errors(tmp_path):
    d = tmp_path / "sprints"
    _write(d, "S01-a.md", "S01", "active")
    (d / "S02-broken.md").write_text("oops", encoding="utf-8")
    sprints, errors = load_sprints(d, strict=False)
    assert [s.id for s in sprints] == ["S01"] and len(errors) == 1
    with pytest.raises(SprintError):
        load_sprints(d)


def test_S01_missing_sprints_dir_is_empty(tmp_path):
    assert load_sprints(tmp_path / "none") == ([], [])
    assert next_sprint_id([]) == "S01"
