"""Phase 2 integration tests: the ratchet in real temp git repos."""

from __future__ import annotations

import json
import time

import pytest

from tests.helpers import BASE_TESTS, FakeProject, T

pytestmark = pytest.mark.slow


@pytest.fixture
def proj(tmp_path, _isolated_home) -> FakeProject:
    return FakeProject(tmp_path / "repo", _isolated_home)


def ratchet_project(proj: FakeProject) -> FakeProject:
    r = proj.init("--ratchet-only", "--no-hooks")
    assert r.code == 0, r.out + r.err
    proj.commit("add sprintwarden")
    return proj


def checks(record) -> dict:
    return {c["id"]: c for c in record["checks"]}


# --------------------------------------------------------------------------- init


def test_S02_init_ratchet_only_is_useful_in_one_command(proj):
    r = proj.init("--ratchet-only", "--no-hooks")
    assert r.code == 0, r.out + r.err
    assert "baseline written: 5 tests" in r.out
    base = proj.read_json(".sprint/baseline.json")
    assert base["reason"] == "init" and len(base["tests"]) == 5
    assert base["tests"]["AuthTest.S01_login"] == "passed"
    for rel in [
        ".sprint/config.toml",
        ".sprint/removals.json",
        ".sprint/skips.json",
        ".sprint/latest.json",
        ".sprint/README.md",
        "AGENTS.md",
        "CLAUDE.md",
        ".gitignore",
        ".gitattributes",
    ]:
        assert (proj.root / rel).exists(), rel
    assert not (proj.root / ".sprint" / "sprints").exists()
    assert ".sprint/out/" in (proj.root / ".gitignore").read_text()
    assert "@AGENTS.md" in (proj.root / "CLAUDE.md").read_text()
    agents = (proj.root / "AGENTS.md").read_text()
    assert "test ratchet" in agents and "accept-removal" in agents
    registry = (proj.home / "registry.toml").read_text()
    assert "repo" in registry
    latest = proj.read_json(".sprint/latest.json")
    assert latest["milestone"] == "init" and latest["result"] == "pass"


def test_S02_init_is_idempotent_and_never_overwrites(proj):
    ratchet_project(proj)
    (proj.root / "AGENTS.md").write_text(
        "# My rules\n\nkeep me\n" + (proj.root / "AGENTS.md").read_text()
    )
    before = (proj.root / ".sprint" / "config.toml").read_text()
    r = proj.sprint("init", "--ratchet-only", "--no-hooks", "--yes")
    assert r.code == 0, r.out + r.err
    assert "config.toml exists" in r.out and "baseline already exists" in r.out
    assert (proj.root / ".sprint" / "config.toml").read_text() == before
    agents = (proj.root / "AGENTS.md").read_text()
    assert agents.startswith("# My rules") and agents.count("sprintwarden:begin") == 1
    assert (proj.root / ".gitignore").read_text().count(".sprint/out/") == 1


def test_S02_init_appends_to_existing_agent_files(proj):
    (proj.root / "AGENTS.md").write_text("# House rules\nUse tabs.\n")
    (proj.root / "CLAUDE.md").write_text("Be terse.\n")
    (proj.root / ".gitignore").write_text("node_modules")
    r = proj.init("--ratchet-only", "--no-hooks", "--no-gate")
    assert r.code == 0, r.out
    assert (proj.root / "AGENTS.md").read_text().startswith("# House rules\nUse tabs.\n")
    assert (proj.root / "CLAUDE.md").read_text() == "Be terse.\n\n@AGENTS.md\n"
    assert (proj.root / ".gitignore").read_text().startswith("node_modules\n")
    assert not (proj.root / ".sprint" / "baseline.json").exists()


def test_S02_init_refuses_baseline_when_tests_fail(proj):
    r = proj.init(
        "--ratchet-only", "--no-hooks", tests=[T("A", "ok"), T("A", "broken", "failed", "nope")]
    )
    assert r.code == 1
    assert "Baseline NOT written" in r.out and "fail today" in r.out
    assert not (proj.root / ".sprint" / "baseline.json").exists()


def test_S02_init_without_xml_explains_runner_problem(proj):
    proj.scenario(BASE_TESTS, no_xml=True)
    proj.commit()
    r = proj.sprint(
        "init",
        "--ratchet-only",
        "--no-hooks",
        "--stack",
        "custom",
        "--command",
        proj.command,
        "--reports",
        "build/*.xml",
    )
    assert r.code == 1
    assert "no JUnit XML found matching build/*.xml" in r.out
    assert "BUILD FAILED" in r.out, "stderr tail of the runner is shown"
    assert "produced no usable JUnit XML" in r.out


def test_S02_init_autodetects_and_requires_a_stack(proj):
    r = proj.sprint("init", "--ratchet-only", "--no-hooks", "--no-gate", "--yes")
    assert r.code == 2 and "no test stack detected" in r.err
    (proj.root / "pytest.ini").write_text("[pytest]\n")
    r = proj.sprint("init", "--ratchet-only", "--no-hooks", "--no-gate", "--yes")
    assert r.code == 0, r.err
    assert 'stack = "pytest"' in (proj.root / ".sprint" / "config.toml").read_text()


# --------------------------------------------------------------------------- gate


def test_S02_green_gate_passes_with_json(proj):
    ratchet_project(proj)
    r = proj.sprint("gate", "--json")
    assert r.code == 0, r.out + r.err
    rec = r.json()
    assert rec["result"] == "pass" and rec["schema"] == 1 and rec["mode"] == "ratchet-only"
    assert rec["totals"] == {"total": 5, "passed": 5, "failed": 0, "skipped": 0}
    assert set(rec["by_sprint"]) == {"legacy", "S01", "S02"}
    assert list(rec["by_sprint"]) == ["legacy", "S01", "S02"]
    assert rec["agent"] == "human" and rec["git"]["head"] and rec["git"]["dirty"] is False
    assert all(c["ok"] for c in rec["checks"])
    run_files = list((proj.root / ".sprint" / "runs").rglob("*.json"))
    assert len(run_files) == 2  # init + this one
    assert proj.read_json(".sprint/latest.json")["id"] == rec["id"]


def test_S02_regression_is_labelled_with_its_sprint(proj):
    ratchet_project(proj)
    tests = [dict(t) for t in BASE_TESTS]
    tests[1] = T("AuthTest", "S01_lockoutAfter5Attempts", "failed", "expected 423 but was 200")
    tests[4] = T("HealthTest", "healthCheck", "error", "boom")
    proj.scenario(tests)
    r = proj.sprint("gate")
    assert r.code == 1
    assert "AuthTest.S01_lockoutAfter5Attempts  ← REGRESSION from sprint S01" in r.out
    assert "HealthTest.healthCheck  ← REGRESSION was passing in baseline" in r.out
    assert "expected 423 but was 200" in r.out
    assert "GATE: FAIL" in r.out
    rec = proj.read_json(".sprint/latest.json")
    assert rec["counts"]["regressions"] == 2
    assert rec["failing"][0]["regression"] is True


def test_S02_deleted_test_fails_until_a_human_accepts_it(proj):
    ratchet_project(proj)
    proj.scenario([t for t in BASE_TESTS if t["name"] != "S02_roundsToPaise"])
    r = proj.sprint("gate")
    assert r.code == 1
    assert "1 test missing vs baseline" in r.out
    assert "InvoiceTest.S02_roundsToPaise" in r.out and "accept-removal" in r.out
    assert "ratchet    4 < 5" in r.out

    # an agent can't accept it
    r = proj.sprint(
        "accept-removal", "InvoiceTest.S02_roundsToPaise", "--reason", "merged", agent="claude-code"
    )
    assert r.code == 2 and "human-only" in r.err
    # a human can, with a reason
    r = proj.sprint(
        "accept-removal", "InvoiceTest.S02_roundsToPaise", "--reason", "merged into roundsToCents"
    )
    assert r.code == 0, r.err
    removals = proj.read_json(".sprint/removals.json")["removals"]
    assert removals[0]["id"] == "InvoiceTest.S02_roundsToPaise" and removals[0]["by"] == "Dev Human"
    r = proj.sprint("gate")
    assert r.code == 0, r.out
    assert "ratchet    4 ≥ 4 (5 - 1 accepted removals)" in r.out


def test_S02_new_skip_fails_until_allowed(proj):
    ratchet_project(proj)
    tests = [dict(t) for t in BASE_TESTS]
    tests[0] = T("AuthTest", "S01_login", "skipped", "flaky")
    tests.append(T("NewTest", "S03_brandNew", "skipped"))
    proj.scenario(tests)
    r = proj.sprint("gate", "--json")
    assert r.code == 1
    rec = r.json()
    assert [s["id"] for s in rec["new_skips"]] == ["AuthTest.S01_login", "NewTest.S03_brandNew"]
    assert rec["new_skips"][0]["was"] == "passed" and rec["new_skips"][1]["was"] == "new"
    r = proj.sprint("allow-skip", "--all-new", "--reason", "flaky upstream; ticket 12")
    assert r.code == 0, r.err
    assert proj.sprint("gate").code == 0


def test_S02_ratchet_drop_fails_even_when_missing_check_is_off(proj):
    ratchet_project(proj)
    proj.config_set("gate", "fail_on_missing_tests", False)
    proj.scenario(BASE_TESTS[:3])
    rec = proj.sprint("gate", "--json").json()
    c = checks(rec)
    assert c["missing"]["ok"] is False and c["missing"]["blocking"] is False
    assert c["ratchet"]["ok"] is False and rec["result"] == "fail"


def test_S02_renamed_test_shows_missing_plus_new(proj):
    ratchet_project(proj)
    tests = [dict(t) for t in BASE_TESTS]
    tests[0] = T("AuthTest", "S01_loginWorks")
    proj.scenario(tests)
    rec = proj.sprint("gate", "--json").json()
    assert [m["id"] for m in rec["missing"]] == ["AuthTest.S01_login"]
    assert rec["new_tests"] == ["AuthTest.S01_loginWorks"]
    assert checks(rec)["ratchet"]["ok"] is True


def test_S02_runner_crash_without_failures_fails_the_gate(proj):
    ratchet_project(proj)
    proj.scenario(BASE_TESTS, exit=3)
    rec = proj.sprint("gate", "--json").json()
    assert checks(rec)["runner"]["ok"] is False
    assert "runner exited 3 but no test failed" in checks(rec)["runner"]["summary"]
    proj.config_set("gate", "fail_on_runner_error", False)
    assert proj.sprint("gate").code == 0


def test_S02_no_xml_marks_other_checks_not_evaluated(proj):
    ratchet_project(proj)
    proj.scenario(BASE_TESTS, no_xml=True)
    r = proj.sprint("gate", "--json")
    rec = r.json()
    c = checks(rec)
    assert c["runner"]["ok"] is False and "BUILD FAILED" in c["runner"]["detail"]
    assert c["failures"]["ok"] is None and c["missing"]["ok"] is None
    assert rec["missing"] == [], "no wall of 'missing' tests when nothing ran"


def test_S02_stale_reports_are_cleaned_but_tracked_files_are_not(proj):
    ratchet_project(proj)
    out = proj.root / ".sprint" / "out"
    (out / "stale.xml").write_text(
        '<testsuite name="old"><testcase classname="Old" name="S01_ghost"/></testsuite>'
    )
    proj.config_set("test", "reports", [".sprint/out/*.xml", "fixtures/*.xml"])
    fixture = proj.root / "fixtures" / "keep.xml"
    fixture.parent.mkdir()
    fixture.write_text('<testsuite name="f"><testcase classname="Fx" name="tracked"/></testsuite>')
    proj.commit("tracked report fixture")
    rec = proj.sprint("gate", "--json").json()
    assert not (out / "stale.xml").exists()
    assert fixture.exists(), "tracked files are never deleted"
    assert rec["totals"]["total"] == 6


def test_S02_no_run_evaluates_existing_reports(proj):
    ratchet_project(proj)
    proj.scenario([T("X", "would_change", "failed")])
    rec = proj.sprint("gate", "--no-run", "--json").json()
    assert rec["ran"] is False and rec["result"] == "pass" and rec["totals"]["total"] == 5


def test_S02_gate_works_from_a_subdirectory(proj):
    ratchet_project(proj)
    sub = proj.root / "src" / "deep"
    sub.mkdir(parents=True)
    r = proj.sprint("gate", cwd=sub)
    assert r.code == 0, r.out + r.err


def test_S02_outside_a_project_is_a_usage_error(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "empty", _isolated_home, git=False)
    r = p.sprint("gate")
    assert r.code == 2 and "not a sprintwarden project" in r.err
    r = p.sprint("gate", "--json")
    assert r.code == 2 and r.json()["ok"] is False


# --------------------------------------------------------------------------- baseline


def test_S02_baseline_requires_clean_head_and_passing_gate(proj):
    ratchet_project(proj)
    proj.scenario(BASE_TESTS + [T("NewTest", "S03_new")])
    r = proj.sprint("baseline")
    assert r.code == 2 and "uncommitted changes" in r.err
    proj.commit("add a test")
    r = proj.sprint("baseline", agent="codex")
    assert r.code == 2 and "human-only" in r.err
    r = proj.sprint("baseline", "--reason", "after review")
    assert r.code == 0, r.out + r.err
    assert "baseline: 6 tests (was 5: +1, -0)" in r.out
    base = proj.read_json(".sprint/baseline.json")
    assert base["reason"] == "baseline: after review" and len(base["tests"]) == 6


def test_S02_baseline_refuses_failing_suite(proj):
    ratchet_project(proj)
    proj.scenario(BASE_TESTS[:-1] + [T("HealthTest", "healthCheck", "failed")])
    proj.commit("break")
    r = proj.sprint("baseline")
    assert r.code == 1 and "Baseline NOT written" in r.out


def test_S02_i_am_human_overrides_the_guard_and_is_recorded(proj):
    ratchet_project(proj)
    r = proj.sprint(
        "allow-skip",
        "AuthTest.S01_login",
        "--reason",
        "quarantine",
        "--i-am-human",
        agent="claude-code",
    )
    assert r.code == 0, r.err
    entry = proj.read_json(".sprint/skips.json")["skips"][0]
    assert entry["by"] == "Dev Human (--i-am-human, in claude-code)"


def test_S02_removal_does_not_exempt_a_test_re_added_later(proj):
    ratchet_project(proj)
    proj.scenario(BASE_TESTS[:-1])
    proj.commit("drop health check")
    assert proj.sprint("accept-removal", "HealthTest.healthCheck", "--reason", "obsolete").code == 0
    proj.commit("accept")
    time.sleep(0.01)
    assert proj.sprint("baseline").code == 0
    proj.commit("rebaseline")
    # re-added and baselined again...
    proj.scenario(BASE_TESTS)
    proj.commit("restore health check")
    time.sleep(0.01)
    assert proj.sprint("baseline").code == 0
    proj.commit("rebaseline 2")
    # ...then deleted again: the old acceptance must not cover it
    proj.scenario(BASE_TESTS[:-1])
    rec = proj.sprint("gate", "--json").json()
    assert [m["id"] for m in rec["missing"]] == ["HealthTest.healthCheck"]


def test_S02_accept_removal_patterns_and_all_missing(proj):
    ratchet_project(proj)
    proj.scenario([t for t in BASE_TESTS if not t["name"].startswith("S01")])
    proj.sprint("gate")
    r = proj.sprint("accept-removal", "--all-missing", "--reason", "auth moved to service")
    assert r.code == 0 and "accepted 2 removals" in r.out
    assert proj.sprint("gate").code == 0
    r = proj.sprint("accept-removal", "/^Invoice/", "--reason", "bulk")
    assert "accepted 2 removals" in r.out
    r = proj.sprint("accept-removal", "Nope.nothing", "--reason", "typo?")
    assert "not in the baseline" in r.out
    assert proj.sprint("accept-removal", "X.y", "--reason", "").code == 2


# --------------------------------------------------------------------------- history / doctor / misc


def test_S02_history_and_retention(proj):
    ratchet_project(proj)
    for _ in range(3):
        assert proj.sprint("gate").code == 0
    r = proj.sprint("history", "--limit", "2", "--json")
    runs = r.json()["runs"]
    assert len(runs) == 2 and runs[0]["result"] == "pass"
    assert "init" in proj.sprint("history").out
    proj.config_set("history", "keep", 2)
    proj.sprint("gate")
    files = sorted((proj.root / ".sprint" / "runs").rglob("*.json"))
    # keep=2 newest, plus the init milestone which is never pruned
    assert len(files) == 3
    assert any(json.loads(f.read_text())["milestone"] == "init" for f in files)


def test_S02_doctor_reports_health(proj):
    ratchet_project(proj)
    r = proj.sprint("doctor")
    assert r.code == 0, r.out
    assert "config.toml parses" in r.out and "baseline: 5 tests" in r.out
    (proj.root / ".sprint" / "config.toml").write_text("[test\n")
    r = proj.sprint("doctor", "--json")
    assert r.code == 2 and r.json()["errors"] == 1


def test_S02_baseline_ref_ignores_tampered_branch_baseline(proj):
    ratchet_project(proj)
    proj.git("checkout", "-q", "-b", "agent-branch")
    # the "agent" deletes a test and edits the baseline to hide it
    proj.scenario(BASE_TESTS[:-1])
    base = proj.read_json(".sprint/baseline.json")
    del base["tests"]["HealthTest.healthCheck"]
    (proj.root / ".sprint" / "baseline.json").write_text(json.dumps(base, indent=2))
    proj.commit("sneaky")
    assert proj.sprint("gate").code == 0, "locally the tampered baseline hides it"
    rec = proj.sprint("gate", "--baseline-ref", "main", "--json").json()
    assert rec["result"] == "fail" and [m["id"] for m in rec["missing"]] == [
        "HealthTest.healthCheck"
    ]
    assert rec["baseline"]["ref"] == "main"
    # an acceptance added on the branch is honoured, and surfaced for review
    assert proj.sprint("accept-removal", "HealthTest.healthCheck", "--reason", "obsolete").code == 0
    rec = proj.sprint("gate", "--baseline-ref", "main", "--json").json()
    assert rec["result"] == "pass"
    assert rec["accepted_in_branch"]["removal"][0]["id"] == "HealthTest.healthCheck"
    md = proj.sprint("gate", "--baseline-ref", "main", "--no-run", "--format", "markdown").out
    assert "Exceptions accepted on this branch" in md


def test_S02_multiple_suites_are_merged(proj):
    ratchet_project(proj)
    web = proj.root / "web"
    web.mkdir()
    (web / "fake_runner.py").write_text((proj.root / "fake_runner.py").read_text())
    (web / "scenario.json").write_text(
        json.dumps({"tests": [T("web", "[S02] renders invoice")], "out": "../.sprint/out/web.xml"})
    )
    cfg = (proj.root / ".sprint" / "config.toml").read_text()
    cfg = cfg.replace(
        'reports  = [".sprint/out/junit.xml"]', 'reports  = [".sprint/out/junit.xml"]'
    )
    cfg += f'\n[[test.suites]]\nname = "web"\ncwd = "web"\ncommand = {json.dumps(proj.command)}\nreports = [".sprint/out/web.xml"]\n'
    (proj.root / ".sprint" / "config.toml").write_text(cfg)
    rec = proj.sprint("gate", "--json").json()
    assert rec["result"] == "pass", rec["checks"]
    assert rec["totals"]["total"] == 6 and rec["by_sprint"]["S02"]["total"] == 3
    assert [r["suite"] for r in rec["runner"]] == ["default", "web"]


def test_S02_works_without_git(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "nogit", _isolated_home, git=False)
    r = p.init("--ratchet-only", "--no-hooks")
    assert r.code == 0, r.out + r.err
    rec = p.sprint("gate", "--json").json()
    assert rec["result"] == "pass" and rec["git"]["head"] is None
    p.scenario(BASE_TESTS[:-1])
    assert p.sprint("gate").code == 1


def test_S02_stale_lock_from_dead_process_is_ignored(proj):
    ratchet_project(proj)
    lock = proj.root / ".sprint" / "out" / "gate.lock"
    lock.write_text(json.dumps({"pid": 999999, "started": "2020-01-01T00:00:00Z"}))
    assert proj.sprint("gate").code == 0
    assert not lock.exists()
