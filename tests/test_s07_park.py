"""Phase S07: parking sprints (status ``parked``), so the board can show what's set aside."""

from __future__ import annotations

import pytest

from sprintwarden.sprintfile import load_sprints, parse_sprint_text, validate_sprints
from tests.helpers import FakeProject, T

pytestmark = pytest.mark.slow

AUTH = [T("AuthTest", "S01_login"), T("HealthTest", "healthCheck")]


@pytest.fixture
def proj(tmp_path, _isolated_home) -> FakeProject:
    """Sprints mode: S01 active, S02 and S03 planned."""
    p = FakeProject(tmp_path / "repo", _isolated_home)
    r = p.init("--no-hooks", "--sprint-title", "Auth", tests=AUTH)
    assert r.code == 0, r.out + r.err
    assert p.sprint("new", "Billing", "--goal", "Invoices round to the cent").code == 0
    assert p.sprint("new", "Reports").code == 0
    p.commit("plan")
    return p


def sprints(p: FakeProject) -> dict:
    found, errors = load_sprints(p.root / ".sprint" / "sprints")
    assert not errors
    return {s.id: s for s in found}


def current(p: FakeProject) -> str:
    return p.sprint("status", "--json").json()["sprint_current"] or ""


def test_S07_park_a_planned_sprint_and_bring_it_back(proj):
    r = proj.sprint("park", "S02", "--reason", "waiting on the tax API", "--json")
    assert r.code == 0, r.out + r.err
    assert r.json() == {"id": "S02", "status": "parked", "changed": True, "was": "planned"}
    s02 = sprints(proj)["S02"]
    assert s02.status == "parked" and s02.parked and s02.parked_reason == "waiting on the tax API"
    assert s02.to_json()["parked_reason"] == "waiting on the tax API"
    note = s02.to_json()["notes"][-1]
    assert note.endswith("Parked: waiting on the tax API (agent: human)"), note

    r = proj.sprint("unpark", "S02")
    assert r.code == 0 and "planned again" in r.out
    s02 = sprints(proj)["S02"]
    assert s02.status == "planned" and not s02.parked and not s02.parked_reason
    assert "Back to planned (was parked since" in s02.to_json()["notes"][-1]
    assert current(proj) == "S01", "parking another sprint leaves the active one alone"


def test_S07_park_the_active_sprint_clears_current_and_start_resumes_it(proj):
    r = proj.sprint("park", "S01", "--json")
    assert r.code == 0 and r.json()["was"] == "active"
    assert sprints(proj)["S01"].status == "parked"
    assert current(proj) == ""
    status = proj.sprint("status")
    assert "No active sprint; start one with `sprint start S02`" in status.out
    assert "Parked: S01" in status.out
    doctor = proj.sprint("doctor", "--json").json()
    assert not [c for c in doctor["checks"] if c["level"] == "error"], doctor

    r = proj.sprint("start", "S01")
    assert r.code == 0, r.out + r.err
    s01 = sprints(proj)["S01"]
    assert s01.status == "active" and not s01.parked and current(proj) == "S01"
    text = s01.path.read_text(encoding="utf-8")
    assert 'parked = ""' in text, "the parked markers are cleared, not left stale"


def test_S07_park_refuses_closed_sprints_and_unpark_needs_a_parked_one(proj):
    s01 = sprints(proj)["S01"].path
    s01.write_text(s01.read_text().replace("tests = []", 'tests = ["S01_login"]'))
    proj.sprint("gate")
    proj.commit("gate")
    r = proj.sprint("close", "S01")
    assert r.code == 0, r.out + r.err
    r = proj.sprint("park", "S01")
    assert r.code == 2 and "can't be parked" in r.err
    r = proj.sprint("unpark", "S03")
    assert r.code == 2 and "not parked" in r.err
    assert proj.sprint("park", "S03").code == 0
    r = proj.sprint("park", "S03", "--json")
    assert r.code == 0 and r.json()["changed"] is False, "parking twice is a no-op"
    assert proj.sprint("park", "S09").code == 2


def test_S07_park_a_parked_sprint_may_list_acs_without_tests(tmp_path):
    text = """+++
id = "S04"
title = "Later"
status = "parked"
parked = 2026-10-12
parked_reason = "not this quarter"

[[ac]]
id = "AC1"
desc = "Someday"
+++
"""
    s = parse_sprint_text(text, tmp_path / "S04-later.md")
    assert s.status == "parked" and s.parked == "2026-10-12"
    assert validate_sprints([s], "") == [], "like planned sprints, parked ones need no tests yet"


def test_S07_park_keeps_the_sprints_tests_in_the_ratchet(proj):
    tests = AUTH + [T("InvoiceTest", "S02_roundsHalfUp")]
    proj.scenario(tests)
    proj.commit("S02 test exists")
    assert proj.sprint("baseline").code == 0
    proj.commit("baseline")
    assert proj.sprint("park", "S02").code == 0
    proj.scenario(AUTH)  # the S02 test disappears while S02 is parked
    r = proj.sprint("gate", "--json")
    assert r.code == 1
    assert [m["id"] for m in r.json()["missing"]] == ["InvoiceTest.S02_roundsHalfUp"]
