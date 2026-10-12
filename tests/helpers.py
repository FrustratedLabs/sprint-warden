"""Integration-test harness: a throwaway git repo whose "test suite" is a tiny
Python script that writes JUnit XML from ``scenario.json``. Tests edit the
scenario to simulate an agent fixing, breaking, deleting or skipping tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAKE_RUNNER = r"""
import json, pathlib, sys
from xml.sax.saxutils import quoteattr
sc = json.loads(pathlib.Path("scenario.json").read_text(encoding="utf-8"))
print("fake runner: running", len(sc.get("tests", [])), "tests")
if sc.get("no_xml"):
    print("BUILD FAILED: cannot compile module", file=sys.stderr)
    sys.exit(sc.get("exit", 1))
out = pathlib.Path(sc.get("out", ".sprint/out/junit.xml"))
out.parent.mkdir(parents=True, exist_ok=True)
cases = []
failed = False
for t in sc["tests"]:
    body = ""
    if t["outcome"] == "failed":
        failed = True
        body = "<failure message=%s>stack trace</failure>" % quoteattr(t.get("message") or "assertion failed")
    elif t["outcome"] == "error":
        failed = True
        body = "<error message=%s/>" % quoteattr(t.get("message") or "boom")
    elif t["outcome"] == "skipped":
        body = "<skipped message=%s/>" % quoteattr(t.get("message") or "skipped")
    cases.append("<testcase classname=%s name=%s time=\"0.001\">%s</testcase>"
                 % (quoteattr(t["classname"]), quoteattr(t["name"]), body))
out.write_text('<?xml version="1.0"?>\n<testsuites><testsuite name="fake">%s</testsuite></testsuites>'
               % "".join(cases), encoding="utf-8")
sys.exit(sc.get("exit", 1 if failed else 0))
"""


def T(classname: str, name: str, outcome: str = "passed", message: str = "") -> dict:
    return {"classname": classname, "name": name, "outcome": outcome, "message": message}


BASE_TESTS = [
    T("AuthTest", "S01_login"),
    T("AuthTest", "S01_lockoutAfter5Attempts"),
    T("InvoiceTest", "S02_roundsToPaise"),
    T("InvoiceTest", "S02_pdf"),
    T("HealthTest", "healthCheck"),
]


@dataclass
class Result:
    code: int
    out: str
    err: str

    def json(self):
        return json.loads(self.out)


class FakeProject:
    def __init__(self, root: Path, home: Path, *, git: bool = True) -> None:
        self.root = root
        self.home = home
        root.mkdir(parents=True, exist_ok=True)
        (root / "fake_runner.py").write_text(FAKE_RUNNER, encoding="utf-8")
        self.git_enabled = git
        if git:
            self.git("init", "-q", "-b", "main")
            self.git("config", "user.email", "dev@example.invalid")
            self.git("config", "user.name", "Dev Human")
            self.git("config", "commit.gpgsign", "false")
            self.git("config", "tag.gpgsign", "false")

    @property
    def command(self) -> str:
        return f'"{sys.executable}" fake_runner.py'

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=check
        )

    def scenario(self, tests: list[dict] | None = None, **extra) -> None:
        data = {"tests": tests if tests is not None else BASE_TESTS, **extra}
        (self.root / "scenario.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def commit(self, message: str = "wip") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def env(self, agent: str = "human", **extra: str) -> dict:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CURSOR", "CODEX"))
        }
        env.pop("AI_AGENT", None)
        env.pop("CI", None)
        env.pop("GITHUB_ACTIONS", None)
        env.pop("GITHUB_HEAD_REF", None)
        env["SPRINT_HOME"] = str(self.home)
        env["SPRINT_AGENT"] = agent
        env["NO_COLOR"] = "1"
        env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # git hooks call `sprint`: make sure it's this checkout's
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        env.update(extra)
        return env

    def sprint(
        self,
        *args: str,
        agent: str = "human",
        stdin: str | None = None,
        cwd: Path | None = None,
        **env,
    ) -> Result:
        proc = subprocess.run(
            [sys.executable, "-m", "sprintwarden", *args],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=stdin,
            env=self.env(agent, **env),
            timeout=120,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def init(self, *extra: str, tests: list[dict] | None = None) -> Result:
        self.scenario(tests)
        if self.git_enabled:
            self.commit("initial")
        return self.sprint(
            "init",
            "--stack",
            "custom",
            "--command",
            self.command,
            "--reports",
            ".sprint/out/junit.xml",
            "--yes",
            *extra,
        )

    def read_json(self, rel: str):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def config_set(self, section: str, key: str, value) -> None:
        sys.path.insert(0, str(REPO))
        from sprintwarden.config import set_value

        set_value(self.root, section, key, value)
