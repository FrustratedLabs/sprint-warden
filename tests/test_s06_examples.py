"""Phase 6: the example projects prove the S01-regression story on several stacks.

The pytest example always runs. Vitest, Go and Gradle need their toolchains and
take a while, so they run when SPRINT_EXAMPLES=1 (CI's examples workflow runs
them all, per stack, with `examples/run-all.sh --require`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO

pytestmark = pytest.mark.slow

RUN_ALL = REPO / "examples" / "run_all.py"


def run_examples(*args: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "SPRINT_"))}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, str(RUN_ALL), *args, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=900,
    )
    data = json.loads(proc.stdout)
    data["exit"] = proc.returncode
    return data


def assert_story(result: dict, stack: str) -> None:
    r = result["results"][stack]
    assert r["status"] == "pass", r.get("error")
    steps = "\n".join(r["steps"])
    assert "main: PASS" in steps and "S02 ACs satisfied" in steps
    assert "s01-regression: FAIL, REGRESSION from sprint S01" in steps
    assert steps.endswith("main again: PASS")


def test_S06_example_pytest_regression_and_cheat_are_caught():
    data = run_examples("pytest")
    assert data["exit"] == 0
    assert_story(data, "pytest")
    assert "agent-cheat: FAIL, missing vs baseline" in "\n".join(data["results"]["pytest"]["steps"])


def _heavy(stack: str, *tools: str):
    if os.environ.get("SPRINT_EXAMPLES") != "1":
        pytest.skip("set SPRINT_EXAMPLES=1 to run the non-Python examples")
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")
    data = run_examples(stack)
    assert data["exit"] == 0
    assert_story(data, stack)


def test_S06_example_vitest_regression_is_caught():
    _heavy("vitest", "node", "npm")


def test_S06_example_go_regression_is_caught():
    _heavy("go", "go")


def test_S06_example_gradle_regression_is_caught():
    _heavy("gradle", "java")


def test_S06_examples_dashboard_shows_status_matrix_and_trends(monkeypatch):
    data = run_examples("pytest", "--keep")
    work = Path(data["work"])
    try:
        monkeypatch.setenv("SPRINT_HOME", data["sprint_home"])
        from sprintwarden.ui.server import list_projects, project_runs

        (proj,) = [p for p in list_projects() if p["project_key"] == "PYINV"]
        assert proj["status"] == "pass" and proj["sprint"]["id"] == "S02"
        assert proj["acs"] == {"satisfied": 2, "total": 2}
        runs = project_runs(proj["key"], 50)
        assert [r["result"] for r in runs] == ["pass", "fail", "fail", "pass", "pass"], (
            "newest first"
        )
        regression_run = runs[2]
        assert regression_run["git"]["branch"] == "s01-regression"
        assert regression_run["by_sprint"]["S01"]["failed"] == 1, (
            "matrix cell S01 × that run is red"
        )
        assert regression_run["failing"][0]["regression_reason"] == "from sprint S01"
        assert [r["milestone"] for r in runs if r.get("milestone")] == ["init"], "trend milestone"
    finally:
        shutil.rmtree(work, ignore_errors=True)
