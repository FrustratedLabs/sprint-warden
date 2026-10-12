"""Phase 3: distribution channels (GitHub Action, Claude Code plugin, CI snippets)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sprintwarden import __version__
from tests.helpers import BASE_TESTS, REPO, FakeProject, T


def action_step_script(step_id: str) -> str:
    """Pull a step's `run: |` block out of action.yml without a YAML library."""
    lines = (REPO / "action.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"id: {step_id}")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    body = []
    indent = None
    for line in lines[run + 1 :]:
        if line.strip() and indent is None:
            indent = len(line) - len(line.lstrip())
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:] if line.strip() else "")
    return "\n".join(body) + "\n"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_S03_action_gate_step_writes_summary_outputs_and_annotations(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "repo", _isolated_home)
    assert p.init("--ratchet-only", "--no-hooks").code == 0
    p.commit("setup")
    script = tmp_path / "gate.sh"
    script.write_text(action_step_script("gate"))

    def run():
        summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
        for f in (summary, output):
            f.write_text("")
        env = p.env(
            "ci",
            SW_BASELINE_REF="none",
            SW_ARGS="",
            SW_BASE_BRANCH="",
            RUNNER_TEMP=str(tmp_path),
            GITHUB_STEP_SUMMARY=str(summary),
            GITHUB_OUTPUT=str(output),
        )
        proc = subprocess.run(
            ["bash", str(script)], cwd=p.root, env=env, capture_output=True, text=True
        )
        outputs = dict(
            line.split("=", 1) for line in output.read_text().splitlines() if "=" in line
        )
        return proc, summary.read_text(), outputs

    proc, summary, outputs = run()
    assert proc.returncode == 0, proc.stderr
    assert outputs["result"] == "pass" and outputs["exit-code"] == "0"
    assert "sprintwarden gate: PASS" in summary and "| ratchet |" in summary
    assert json.loads((tmp_path / "sprintwarden-gate.json").read_text())["trigger"] == "ci"
    assert (p.root / ".sprint" / "out" / "artifacts" / ".sprint" / "out" / "junit.xml").exists()

    tests = [dict(t) for t in BASE_TESTS[:-1]]
    tests[0] = T("AuthTest", "S01_login", "failed", "boom")
    p.scenario(tests)
    proc, summary, outputs = run()
    assert proc.returncode == 0, "the script itself never fails; a later step does"
    assert outputs["result"] == "fail" and outputs["exit-code"] == "1"
    assert outputs["regressions"] == "1" and outputs["missing"] == "1"
    assert "::error title=sprintwarden REGRESSION [S01]::AuthTest.S01_login: boom" in proc.stdout
    assert "::error title=sprintwarden missing test [legacy]::HealthTest.healthCheck" in proc.stdout
    assert "### Failing tests" in summary and "**REGRESSION**" in summary


def test_S03_action_metadata():
    text = (REPO / "action.yml").read_text(encoding="utf-8")
    assert re.search(r"^runs:\n  using: composite", text, re.M)
    for name in (
        "working-directory",
        "args",
        "baseline-ref",
        "python-version",
        "version",
        "upload-artifacts",
    ):
        assert re.search(rf"^  {re.escape(name)}:\n", text, re.M), name
    assert "actions/upload-artifact@v4" in text and "GITHUB_STEP_SUMMARY" in text


def test_S03_plugin_and_marketplace_are_consistent():
    plugin = json.loads((REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    entry = market["plugins"][0]
    assert entry["name"] == plugin["name"] == "sprintwarden"
    assert entry["source"] == "./plugin"
    assert plugin["version"] == entry["version"] == __version__.split(".dev")[0]
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"Stop", "SessionStart", "PreToolUse"}
    commands = [h["command"] for event in hooks.values() for e in event for h in e["hooks"]]
    assert all("${CLAUDE_PLUGIN_ROOT}/scripts/sprint.sh" in c for c in commands)
    assert hooks["Stop"][0]["hooks"][0]["timeout"] == 1800
    assert (
        (REPO / "plugin" / "commands" / "sprint-status.md")
        .read_text()
        .startswith("---\ndescription:")
    )
    skill = (REPO / "plugin" / "skills" / "sprint-workflow" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: sprint-workflow\ndescription:")


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
def test_S03_plugin_launcher_finds_the_cli(tmp_path):
    import sys

    env = dict(
        os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    )
    r = subprocess.run(
        ["sh", str(REPO / "plugin" / "scripts" / "sprint.sh"), "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0 and r.stdout.startswith("sprintwarden")
    # without the CLI it never blocks the session
    r = subprocess.run(
        [shutil.which("sh"), str(REPO / "plugin" / "scripts" / "sprint.sh"), "gate", "--hook"],
        capture_output=True,
        text=True,
        env={"PATH": "/nonexistent"},
        cwd=tmp_path,
    )
    assert r.returncode == 0


def test_S03_ci_templates_ship_in_the_package():
    from importlib import resources

    ci = resources.files("sprintwarden").joinpath("templates", "ci")
    names = {e.name for e in ci.iterdir()}
    assert {"sprint-gate.sh", "gitlab-ci.yml", "Jenkinsfile"} <= names
