"""Phase S08: the test command runs with the project's own toolchain.

The gate is started by hooks, git and CI with whatever PATH they have, so a bare
`python` can be the wrong interpreter (Python 2, none at all, or a Python without
the project's dependencies). These tests build that situation with fake
executables on a controlled PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from tests.helpers import BASE_TESTS, FakeProject

pytestmark = pytest.mark.slow

WIN = os.name == "nt"
BIN = "Scripts" if WIN else "bin"


def make_exe(folder: Path, name: str, posix: str, windows: str) -> Path:
    """A tiny executable called `name` in `folder` (a .cmd file on Windows)."""
    folder.mkdir(parents=True, exist_ok=True)
    if WIN:
        path = folder / f"{name}.cmd"
        path.write_text("@echo off\r\n" + windows.replace("\n", "\r\n") + "\r\n", encoding="utf-8")
    else:
        path = folder / name
        path.write_text("#!/bin/sh\n" + posix + "\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def fake_python(folder: Path, marker: str) -> None:
    """`python` that records which copy ran the tests, then runs the real interpreter."""
    make_exe(
        folder,
        "python",
        f'case "$*" in *fake_runner*) echo {marker} >> python-used.txt ;; esac\n'
        f'exec "{sys.executable}" "$@"',
        f'echo %* | findstr fake_runner >nul && (echo {marker}>> python-used.txt)\n"{sys.executable}" %*',
    )


def python2(folder: Path) -> None:
    """`python` that answers the version probe like Python 2.7 and can't run pytest."""
    make_exe(
        folder,
        "python",
        'case "$*" in *version_info*) echo 2.7 ;; *) echo "No module named pytest" >&2; exit 1 ;; esac',
        "echo %* | findstr version_info >nul && (echo 2.7) || (echo No module named pytest 1>&2 & exit /b 1)",
    )


def make_venv(root: Path, name: str = ".venv") -> Path:
    venv = root / name
    venv.mkdir(parents=True, exist_ok=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    fake_python(venv / BIN, name)
    return venv / BIN


_BASE: list[str] = []


def base_path() -> str:
    """A PATH with git (the gate needs it) and nothing else, so no python is on it."""
    if not _BASE:
        folder = Path(tempfile.mkdtemp(prefix="sw-s08-path-"))
        git = shutil.which("git")
        assert git, "these tests need git"
        if WIN:
            _BASE.append(str(Path(git).parent))  # git's own folder has no python
            _BASE.append(os.environ.get("SYSTEMROOT", r"C:\Windows") + r"\System32")
        else:
            (folder / "git").symlink_to(git)
            _BASE.append(str(folder))
    return os.pathsep.join(_BASE)


@pytest.fixture
def proj(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "repo", _isolated_home)
    p.scenario(BASE_TESTS)
    p.commit("initial")
    r = p.sprint(
        "init",
        "--ratchet-only",
        "--no-hooks",
        "--stack",
        "custom",
        "--command",
        "python fake_runner.py",
        "--reports",
        ".sprint/out/junit.xml",
        "--yes",
        PATH=os.pathsep.join([str(Path(sys.executable).parent), base_path()]),
    )
    assert r.code == 0, r.out + r.err
    p.commit("sprintwarden")
    return p


def used(p: FakeProject) -> list[str]:
    f = p.root / "python-used.txt"
    return f.read_text(encoding="utf-8").split() if f.exists() else []


def gate(p: FakeProject, path: str, *args: str, **env: str):
    return p.sprint("gate", "--json", *args, PATH=path, **env)


# --------------------------------------------------------------------------- AC1


def test_S08_venv_dot_venv_comes_first_even_when_python_on_path_is_python2(proj, tmp_path):
    python2(tmp_path / "system")
    make_venv(proj.root)
    r = gate(proj, os.pathsep.join([str(tmp_path / "system"), base_path()]))
    assert r.code == 0, r.out + r.err
    assert used(proj) == [".venv"], "the project's .venv/python ran, not the system one"
    rec = r.json()
    assert rec["result"] == "pass" and rec["totals"]["total"] == len(BASE_TESTS)


def test_S08_venv_plain_venv_folder_and_virtual_env_are_found(proj, tmp_path):
    make_venv(proj.root, "venv")
    assert gate(proj, base_path()).code == 0
    assert used(proj) == ["venv"]
    (proj.root / "python-used.txt").unlink()
    outside = tmp_path / "elsewhere-env"
    (outside).mkdir()
    (outside / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    fake_python(outside / BIN, "VIRTUAL_ENV")
    (proj.root / "venv" / "pyvenv.cfg").unlink()  # no longer a venv
    assert gate(proj, base_path(), VIRTUAL_ENV=str(outside)).code == 0
    assert used(proj) == ["VIRTUAL_ENV"]


def test_S08_venv_projects_without_one_run_exactly_as_before(proj):
    r = gate(proj, os.pathsep.join([str(Path(sys.executable).parent), base_path()]))
    assert r.code == 0, r.out + r.err
    assert used(proj) == [], "no fake python anywhere: the PATH python ran"


# --------------------------------------------------------------------------- AC2


def test_S08_test_path_folders_go_first_and_use_venv_false_turns_the_lookup_off(proj, tmp_path):
    make_venv(proj.root)
    fake_python(proj.root / "tools" / "py", "tools")
    proj.config_set("test", "path", ["tools/py"])
    assert gate(proj, base_path()).code == 0
    assert used(proj) == ["tools"], "test.path wins over the auto-found .venv"
    (proj.root / "python-used.txt").unlink()
    proj.config_set("test", "path", [])
    proj.config_set("test", "use_venv", False)
    python2(tmp_path / "system")
    r = gate(proj, os.pathsep.join([str(tmp_path / "system"), base_path()]))
    assert used(proj) == [] and r.code == 1, ".venv is ignored when use_venv = false"


def test_S08_test_path_rejects_a_path_outside_the_repo(proj):
    proj.config_set("test", "path", ["../outside"])
    r = proj.sprint("gate")
    assert r.code == 2 and "test.path" in r.err and "inside the repo" in r.err


# --------------------------------------------------------------------------- AC3


def test_S08_interpreter_python2_is_named_instead_of_no_junit_xml(proj, tmp_path):
    python2(tmp_path / "system")
    r = gate(proj, os.pathsep.join([str(tmp_path / "system"), base_path()]))
    assert r.code == 1
    runner = next(c for c in r.json()["checks"] if c["id"] == "runner")
    assert "`python` is Python 2.7" in runner["summary"], runner
    assert ".venv" in runner["detail"] and "test.path" in runner["detail"], "says how to fix it"
    assert "no JUnit XML" not in runner["summary"]


def test_S08_interpreter_missing_python_is_named(proj):
    r = gate(proj, base_path())
    runner = next(c for c in r.json()["checks"] if c["id"] == "runner")
    assert r.code == 1 and "`python` was not found on PATH" in runner["summary"], runner


def test_S08_interpreter_missing_runner_module_gets_a_hint(proj, tmp_path):
    # a real Python 3 without pytest installed: the command can't start
    proj.config_set("test", "command", "python -m pytest_not_installed_here")
    fake_python(tmp_path / "py3", "system")
    r = gate(proj, os.pathsep.join([str(tmp_path / "py3"), base_path()]))
    runner = next(c for c in r.json()["checks"] if c["id"] == "runner")
    assert "pytest_not_installed_here" in runner["detail"]
    assert "install the test dependencies" in runner["detail"], runner


# --------------------------------------------------------------------------- AC4


def test_S08_doctor_shows_the_interpreter_the_gate_will_use(proj, tmp_path):
    venv_bin = make_venv(proj.root)
    r = proj.sprint("doctor", PATH=base_path())
    assert f"test PATH starts with {Path('.venv') / BIN} (project virtualenv)" in r.out, r.out
    assert "python" in r.out and str(venv_bin.name) in r.out
    (proj.root / ".venv" / "pyvenv.cfg").unlink()
    python2(tmp_path / "system")
    r = proj.sprint("doctor", PATH=os.pathsep.join([str(tmp_path / "system"), base_path()]))
    assert "`python` is Python 2.7" in r.out, r.out


# --------------------------------------------------------------------------- AC5


def stop(p: FakeProject, path: str, active: bool, session: str = "s1"):
    payload = {"session_id": session, "stop_hook_active": active, "cwd": str(p.root)}
    return p.sprint("gate", "--hook", stdin=json.dumps(payload), agent="claude-code", PATH=path)


def test_S08_hook_reports_an_environment_problem_once_then_lets_go(proj, tmp_path):
    python2(tmp_path / "system")
    path = os.pathsep.join([str(tmp_path / "system"), base_path()])
    first = stop(proj, path, active=False)
    assert first.code == 2 and "Python 2.7" in first.err
    assert "environment" in first.err and "tell the human" in first.err
    # the agent replies; nothing changed: let it stop, and tell the human
    again = stop(proj, path, active=True)
    assert again.code == 0, again.err
    assert "couldn't run" in json.loads(again.out)["systemMessage"]
    # a new user turn on the same unchanged tree doesn't start the nagging again
    assert stop(proj, path, active=False).code == 0
    # once the environment is fixed and the tree changes, the gate runs and passes
    make_venv(proj.root)
    assert stop(proj, path, active=False).code == 0
    assert used(proj) == [".venv"]


def test_S08_hook_still_blocks_build_and_test_failures(proj):
    path = os.pathsep.join([str(Path(sys.executable).parent), base_path()])
    proj.scenario(BASE_TESTS, no_xml=True)  # e.g. the agent broke the build
    assert stop(proj, path, active=False).code == 2
    assert stop(proj, path, active=True).code == 2, "a broken build is the agent's to fix"
    assert stop(proj, path, active=False).code == 2, "and a new turn blocks again"
