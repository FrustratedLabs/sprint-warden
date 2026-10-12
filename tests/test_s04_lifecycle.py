"""Phase 4: the sprints layer (new, start, close, note, ACs in the gate)."""

from __future__ import annotations

import json
import re

import pytest

from tests.helpers import BASE_TESTS, FakeProject, T

pytestmark = pytest.mark.slow

AUTH = [T("AuthTest", "S01_login"), T("AuthTest", "S01_lockout"), T("HealthTest", "healthCheck")]


def write_sprint(p: FakeProject, name: str, body: str) -> None:
    (p.root / ".sprint" / "sprints" / name).write_text(body, encoding="utf-8")


S01 = """+++
id = "S01"
title = "Auth"
status = "active"
goal = "Users can log in"
started = 2026-10-01
closed = ""

[[ac]]
id = "AC1"
desc = "Login works"
tests = ["S01_login"]

[[ac]]
id = "AC2"
desc = "Lockout after 5 attempts"
tests = ["/S01_lock.*/"]
+++

## Notes / decisions
"""


@pytest.fixture
def proj(tmp_path, _isolated_home) -> FakeProject:
    """A sprints-mode project with an active S01 that has two ACs."""
    p = FakeProject(tmp_path / "repo", _isolated_home)
    r = p.init("--no-hooks", "--sprint-title", "Auth", tests=AUTH)
    assert r.code == 0, r.out + r.err
    for f in (p.root / ".sprint" / "sprints").glob("*.md"):
        f.unlink()
    write_sprint(p, "S01-auth.md", S01)
    p.commit("sprint S01")
    return p


def gate(p: FakeProject):
    r = p.sprint("gate", "--json")
    return r.code, r.json()


def check(rec, cid):
    return next(c for c in rec["checks"] if c["id"] == cid)


# --------------------------------------------------------------------------- new / start


def test_S04_new_creates_the_next_numbered_planned_sprint(proj):
    r = proj.sprint("new", "Billing", "v2", "--goal", "Invoices round correctly")
    assert r.code == 0, r.err
    path = proj.root / ".sprint" / "sprints" / "S02-billing-v2.md"
    text = path.read_text()
    assert 'status  = "planned"' in text and 'goal    = "Invoices round correctly"' in text
    assert "S02_doesThing" in text
    assert proj.sprint("new", "Reports", "--json").json()["id"] == "S03"


def test_S04_new_requires_sprints_mode(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "r", _isolated_home)
    assert p.init("--ratchet-only", "--no-hooks").code == 0
    r = p.sprint("new", "x")
    assert r.code == 2 and "ratchet-only mode" in r.err


def test_S04_start_activates_exactly_one_sprint(proj):
    proj.sprint("new", "Billing")
    r = proj.sprint("start", "S02")
    assert r.code == 2 and "S01 is active" in r.err and "sprint close S01" in r.err
    r = proj.sprint("start", "S9")
    assert r.code == 2 and "no sprint S9" in r.err


def test_S04_start_sets_current_dates_and_refreshes_agent_rules(proj):
    (proj.root / ".sprint" / "sprints" / "S01-auth.md").write_text(
        S01.replace('status = "active"', 'status = "closed"')
    )
    proj.config_set("sprint", "current", "")
    proj.sprint("new", "Billing")
    r = proj.sprint("start", "s2")
    assert r.code == 0, r.err
    assert 'current = "S02"' in (proj.root / ".sprint" / "config.toml").read_text()
    text = (proj.root / ".sprint" / "sprints" / "S02-billing.md").read_text()
    assert 'status  = "active"' in text and re.search(r"started = \d{4}-\d\d-\d\d", text)
    assert "e.g. `S02_doesThing`" in (proj.root / "AGENTS.md").read_text()
    assert "no AC lists tests yet" in r.out
    assert proj.sprint("start", "S02").code == 0, "re-starting the active sprint is a no-op"
    r = proj.sprint("start", "S01")
    assert r.code == 2 and "closed" in r.err


# --------------------------------------------------------------------------- gate


def test_S04_gate_computes_ac_state_from_passing_tests(proj):
    code, rec = gate(proj)
    assert code == 0
    assert [(a["id"], a["state"]) for a in rec["acs"]] == [
        ("AC1", "satisfied"),
        ("AC2", "satisfied"),
    ]
    assert check(rec, "sprint_tests")["ok"] is True
    proj.scenario(
        [
            T("AuthTest", "S01_login"),
            T("AuthTest", "S01_lockout", "failed"),
            T("HealthTest", "healthCheck"),
        ]
    )
    code, rec = gate(proj)
    assert code == 1
    assert [(a["id"], a["state"]) for a in rec["acs"]] == [("AC1", "satisfied"), ("AC2", "failing")]
    acs = check(rec, "acs")
    assert acs["ok"] is False and acs["blocking"] is False, "ACs only block close"
    latest = proj.read_json(".sprint/latest.json")
    assert {(a["sprint"], a["id"]) for a in latest["acs_all"]} == {("S01", "AC1"), ("S01", "AC2")}


def test_S04_gate_unsatisfied_acs_alone_do_not_fail_the_gate(proj):
    write_sprint(
        proj, "S01-auth.md", S01.replace('tests = ["S01_login"]', 'tests = ["S01_notWrittenYet"]')
    )
    code, rec = gate(proj)
    assert code == 0 and rec["acs"][0]["state"] == "no-tests"
    assert "AC1 ∅" in proj.sprint("gate", "--no-run").out


def test_S04_gate_requires_tests_for_the_active_sprint(proj):
    proj.scenario(
        [T("HealthTest", "healthCheck"), T("AuthTest", "S01_login"), T("AuthTest", "S01_lockout")]
    )
    write_sprint(
        proj,
        "S01-auth.md",
        S01.replace('status = "active"', 'status = "closed"\nclosed = 2026-10-05').replace(
            'closed = ""\n', ""
        ),
    )
    write_sprint(
        proj,
        "S02-billing.md",
        '+++\nid = "S02"\ntitle = "Billing"\nstatus = "active"\nstarted = 2026-10-06\n+++\n',
    )
    proj.config_set("sprint", "current", "S02")
    code, rec = gate(proj)
    assert code == 1
    c = check(rec, "sprint_tests")
    assert c["ok"] is False and c["blocking"] and "S02_doesThing" in c["detail"]
    proj.config_set("gate", "require_current_sprint_tests", False)
    assert gate(proj)[0] == 0


def test_S04_gate_labels_regressions_from_earlier_and_closed_sprints(proj):
    proj.git("rm", "-q", "--cached", ".sprint/baseline.json")
    (proj.root / ".sprint" / "baseline.json").unlink()  # no baseline: attribution alone decides
    write_sprint(
        proj,
        "S01-auth.md",
        S01.replace('status = "active"', 'status = "closed"\nclosed = 2026-10-05').replace(
            'closed = ""\n', ""
        ),
    )
    write_sprint(
        proj,
        "S02-billing.md",
        '+++\nid = "S02"\ntitle = "Billing"\nstatus = "active"\nstarted = 2026-10-06\n+++\n',
    )
    proj.config_set("sprint", "current", "S02")
    proj.scenario(
        [
            T("AuthTest", "S01_login", "failed"),
            T("BillTest", "S02_new", "failed"),
            T("HealthTest", "healthCheck", "failed"),
        ]
    )
    _, rec = gate(proj)
    labels = {f["id"]: (f["regression"], f.get("regression_reason")) for f in rec["failing"]}
    assert labels["AuthTest.S01_login"] == (True, "from sprint S01")
    assert labels["BillTest.S02_new"] == (False, None), "current sprint work in progress"
    assert labels["HealthTest.healthCheck"] == (False, None), "legacy without a baseline: unknown"


# --------------------------------------------------------------------------- close


def test_S04_close_is_human_only_and_needs_a_clean_head(proj):
    r = proj.sprint("close", "S01", agent="cursor")
    assert r.code == 2 and "human-only" in r.err
    (proj.root / "wip.txt").write_text("x")
    r = proj.sprint("close", "S01")
    assert r.code == 2 and "uncommitted changes" in r.err
    (proj.root / "wip.txt").unlink()
    r = proj.sprint("close", "S02")
    assert r.code == 2 and "no sprint S02" in r.err


def test_S04_close_refuses_unsatisfied_acs(proj):
    write_sprint(proj, "S01-auth.md", S01.replace('tests = ["S01_login"]', 'tests = ["S01_mfa"]'))
    proj.commit("add AC without tests")
    r = proj.sprint("close", "S01")
    assert r.code == 1
    assert "not closed: 1 acceptance criterion not satisfied" in r.out
    assert "AC1 Login works (no matching tests)" in r.out
    assert 'status = "active"' in (proj.root / ".sprint" / "sprints" / "S01-auth.md").read_text()
    assert proj.git("tag", "-l").stdout.strip() == ""


def test_S04_close_refuses_a_failing_gate(proj):
    proj.scenario(
        [
            T("AuthTest", "S01_login"),
            T("AuthTest", "S01_lockout"),
            T("HealthTest", "healthCheck", "failed"),
        ]
    )
    proj.commit("break legacy")
    r = proj.sprint("close", "S01")
    assert r.code == 1 and "not closed: the gate fails" in r.out


def test_S04_close_baselines_tags_and_updates_changelog(proj):
    (proj.root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n- old\n"
    )
    proj.scenario(AUTH + [T("AuthTest", "S01_newEdgeCase")])
    proj.commit("more tests")
    r = proj.sprint("close", "S01", "--json")
    assert r.code == 0, r.out + r.err
    data = r.json()
    assert data["closed"] and data["tag"] == "sprint-S01" and data["commit"]
    assert data["by"] == "Dev Human"
    sprint = (proj.root / ".sprint" / "sprints" / "S01-auth.md").read_text()
    assert 'status = "closed"' in sprint and re.search(r"closed = \d{4}-\d\d-\d\d", sprint)
    assert 'current = ""' in (proj.root / ".sprint" / "config.toml").read_text()
    base = proj.read_json(".sprint/baseline.json")
    assert base["reason"] == "close S01" and base["sprint"] == "S01" and len(base["tests"]) == 4
    changelog = (proj.root / "CHANGELOG.md").read_text()
    assert (
        changelog.index("## [Unreleased]")
        < changelog.index("### Sprint S01: Auth")
        < changelog.index("## [1.0.0]")
    )
    assert (
        "- AC2: Lockout after 5 attempts" in changelog
        and "Tests: 4 (+1 since the previous baseline)" in changelog
    )
    assert proj.git("tag", "-l").stdout.split() == ["sprint-S01"]
    assert proj.git("status", "--porcelain").stdout.strip() == "", "closing changes are committed"
    log = proj.git("log", "-1", "--format=%B").stdout
    assert log.startswith("sprint: close S01 (Auth)") and "Closed by: Dev Human" in log
    latest = proj.read_json(".sprint/latest.json")
    assert latest["milestone"] == "close S01"
    r = proj.sprint("close", "S01")
    assert r.code == 2 and "not the active, current sprint" in r.err


def test_S04_close_creates_a_changelog_and_supports_no_commit_no_tag(proj):
    r = proj.sprint("close", "S01", "--no-commit", "--no-tag")
    assert r.code == 0, r.out + r.err
    assert (proj.root / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## Sprint S01: Auth")
    assert proj.git("tag", "-l").stdout.strip() == ""
    assert proj.git("status", "--porcelain").stdout.strip() != ""


def test_S04_close_no_run_reuses_a_matching_gate_run(proj):
    assert proj.sprint("gate").code == 0
    r = proj.sprint("close", "S01", "--no-run")
    assert r.code == 0, r.out + r.err
    assert "parsed" in r.out


def test_S04_close_no_run_rejects_a_stale_gate(proj):
    assert proj.sprint("gate").code == 0
    proj.scenario(AUTH + [T("X", "S01_more")])
    proj.commit("changed since")
    r = proj.sprint("close", "S01", "--no-run")
    assert r.code == 2 and "doesn't match this tree" in r.err


def test_S04_close_refuses_if_the_tag_exists(proj):
    proj.git("tag", "sprint-S01")
    r = proj.sprint("close", "S01")
    assert r.code == 2 and "already exists" in r.err


# --------------------------------------------------------------------------- status / note


def test_S04_status_shows_sprint_acs_and_regressions_per_sprint(proj):
    r = proj.sprint("status")
    assert "Sprint S01 · Auth · active since 2026-10-01" in r.out
    assert "Goal: Users can log in" in r.out
    assert "stale: HEAD moved" in r.out, "init's gate ran before the sprint file was committed"
    proj.sprint("gate")
    r = proj.sprint("status")
    assert "✓ AC1" in r.out and "✓ AC2" in r.out and "(current)" in r.out
    proj.scenario(
        [
            T("AuthTest", "S01_login", "failed"),
            T("AuthTest", "S01_lockout", "failed"),
            T("HealthTest", "healthCheck", "failed"),
        ]
    )
    proj.sprint("gate")
    r = proj.sprint("status")
    assert "regressions by sprint: legacy ×1, S01 ×2" in r.out
    assert "✗ AC1" in r.out and "1 test, 1 not passing" in r.out
    s = proj.sprint("status", "--json").json()
    assert s["sprint"]["id"] == "S01" and s["sprint"]["acs_state"][0]["state"] == "failing"
    proj.scenario(AUTH + [T("Y", "S01_y")])
    assert "stale: files changed" in proj.sprint("status").out


def test_S04_note_appends_with_agent_name(proj):
    r = proj.sprint("note", "chose", "bcrypt", "over", "argon2", agent="codex")
    assert r.code == 0 and "agent: codex" in r.out
    text = (proj.root / ".sprint" / "sprints" / "S01-auth.md").read_text()
    assert re.search(r"- \d{4}-\d\d-\d\d: chose bcrypt over argon2 \(agent: codex\)\n", text)
    proj.config_set("sprint", "current", "")
    write_sprint(proj, "S01-auth.md", S01.replace('status = "active"', 'status = "planned"'))
    r = proj.sprint("note", "nothing active")
    assert r.code == 2 and "no active sprint" in r.err


def test_S04_status_and_doctor_flag_inconsistent_sprint_state(proj):
    proj.config_set("sprint", "current", "S07")
    r = proj.sprint("doctor")
    assert r.code == 2 and "active sprint is S01 but config sprint.current is S07" in r.out


def test_S04_export_includes_full_sprints_and_history(proj):
    proj.sprint("gate")
    data = proj.sprint("export").json()
    assert data["sprints_full"][0]["acs"][1]["tests"] == ["/S01_lock.*/"]
    assert data["history"] and data["latest_full"]["result"] == "pass"
    md = proj.sprint("export", "--format", "markdown").out
    assert md.startswith("## ✅ sprintwarden gate: PASS")


# --------------------------------------------------------------------------- end to end


def test_S04_full_lifecycle_across_sprints(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "life", _isolated_home)
    # a legacy project adopts sprintwarden in sprints mode
    r = p.init("--no-hooks", "--sprint-title", "Auth", tests=[T("Legacy", "works")])
    assert r.code == 0, "setup succeeded and the legacy tests are baselined..."
    assert "no tests named for S01 yet" in r.out, "...while the gate already asks for S01 tests"
    assert p.read_json(".sprint/baseline.json")["tests"] == {"Legacy.works": "passed"}
    s01 = next((p.root / ".sprint" / "sprints").glob("S01-*.md"))
    s01.write_text(s01.read_text().replace("tests = []", 'tests = ["S01_login"]'))
    p.scenario([T("Legacy", "works"), T("AuthTest", "S01_login")])
    p.commit("S01 work")
    assert p.sprint("close", "S01").code == 0
    # sprint 2
    assert p.sprint("new", "Billing").code == 0
    s02 = p.root / ".sprint" / "sprints" / "S02-billing.md"
    s02.write_text(s02.read_text().replace("tests = []", 'tests = ["S02_rounds"]'))
    assert p.sprint("start", "S02").code == 0
    # the agent's S02 change breaks S01
    p.scenario(
        [
            T("Legacy", "works"),
            T("AuthTest", "S01_login", "failed", "401"),
            T("BillTest", "S02_rounds"),
        ]
    )
    r = p.sprint("gate")
    assert r.code == 1 and "AuthTest.S01_login  ← REGRESSION from sprint S01" in r.out
    p.scenario([T("Legacy", "works"), T("AuthTest", "S01_login"), T("BillTest", "S02_rounds")])
    p.commit("S02 done")
    r = p.sprint("close", "S02")
    assert r.code == 0, r.out + r.err
    assert p.git("tag", "-l").stdout.split() == ["sprint-S01", "sprint-S02"]
    history = p.sprint("history", "--json").json()["runs"]
    assert [h["milestone"] for h in history if h["milestone"]] == ["close S02", "close S01", "init"]
    assert set(json.loads((p.root / ".sprint" / "baseline.json").read_text())["tests"]) == {
        "Legacy.works",
        "AuthTest.S01_login",
        "BillTest.S02_rounds",
    }
    assert "BASE_TESTS" and BASE_TESTS  # shared fixture data stays importable
