"""Found while dogfooding S05: tests that only run on some machines (no browser,
other OS) need a skip allowance that survives re-baselining."""

from __future__ import annotations

import time

import pytest

from tests.helpers import BASE_TESTS, FakeProject, T
from tests.test_s02_ratchet import ratchet_project

pytestmark = pytest.mark.slow


@pytest.fixture
def proj(tmp_path, _isolated_home) -> FakeProject:
    return FakeProject(tmp_path / "repo", _isolated_home)


def test_S05_permanent_skip_survives_rebaselines_for_environment_dependent_tests(proj):
    ratchet_project(proj)
    # on another machine the test can't run (e.g. no browser): it shows up skipped
    env_skipped = [dict(t) for t in BASE_TESTS]
    env_skipped[0] = T("AuthTest", "S01_login", "skipped", "needs Chromium")
    assert (
        proj.sprint(
            "allow-skip",
            "AuthTest.S01_login",
            "--reason",
            "only runs where Chromium is installed",
            "--permanent",
        ).code
        == 0
    )
    assert proj.read_json(".sprint/skips.json")["skips"][0]["permanent"] is True
    proj.commit("allow env skip")
    time.sleep(0.01)
    assert proj.sprint("baseline").code == 0  # re-baselined where it passes
    proj.commit("rebaseline")
    proj.scenario(env_skipped)
    assert proj.sprint("gate").code == 0, (
        "a permanent allowance still applies after the new baseline"
    )


def test_S05_ordinary_skip_allowance_expires_at_the_next_baseline(proj):
    ratchet_project(proj)
    skipped = [dict(t) for t in BASE_TESTS]
    skipped[0] = T("AuthTest", "S01_login", "skipped")
    assert proj.sprint("allow-skip", "AuthTest.S01_login", "--reason", "flaky for now").code == 0
    proj.commit("allow")
    time.sleep(0.01)
    assert proj.sprint("baseline").code == 0  # test passes again; baselined as passed
    proj.commit("rebaseline")
    proj.scenario(skipped)
    assert proj.sprint("gate").code == 1, "skipping it again needs a new approval"
