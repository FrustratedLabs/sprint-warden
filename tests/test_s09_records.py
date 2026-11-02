"""S09: what the gate writes to .sprint/ carries no machine details (D-033).

Each test runs the real gate on a throwaway project inside a fake home folder,
with a long temp folder of its own, on a suite whose failing tests' messages name
the project, the home folder, temp folders, the login and the host. Then it reads
back the run record and latest.json."""

from __future__ import annotations

import getpass
import json
import os
import re
import socket
import sys
from pathlib import Path

import pytest
from helpers import BASE_TESTS, FakeProject, T

SEP = os.sep


def encode(path: str) -> str:
    """How tools such as Claude Code name a folder after a path."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def strings(obj):
    """Every string in a JSON value, keys included."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)


LOGIN = getpass.getuser()
HOST = socket.gethostname()
HAS_LOGIN = len(LOGIN) >= 3
HAS_HOST = len(HOST) >= 3 and HOST.lower() != "localhost"


@pytest.fixture
def home(tmp_path) -> Path:
    folder = tmp_path / "home" / "ada"
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def tmp(tmp_path) -> Path:
    """A temp folder as long as macOS's /var/folders/… one, so it can be cut short."""
    folder = tmp_path / "tmp" / "T-0123456789abcdef"
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def proj(home, _isolated_home) -> FakeProject:
    p = FakeProject(home / "Desktop" / "proj", _isolated_home)
    r = p.init("--ratchet-only", "--no-hooks")
    assert r.code == 0, r.out + r.err
    p.commit("add sprintwarden")
    return p


def machine_env(home: Path, tmp: Path) -> dict[str, str]:
    return {"HOME": str(home), "USERPROFILE": str(home), "TMPDIR": str(tmp)}


def newest_run(proj: FakeProject) -> dict:
    files = sorted((proj.root / ".sprint" / "runs").rglob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) | {"_file": files[-1].stem}


def gate(proj: FakeProject, home: Path, tmp: Path, messages: list[str]) -> list[str]:
    """Run the gate on a suite whose new failing tests carry ``messages``; return
    those messages as the run record wrote them (and check latest.json agrees)."""
    tests = BASE_TESTS + [T("PathTest", f"case{i}", "failed", m) for i, m in enumerate(messages)]
    proj.scenario(tests)
    r = proj.sprint("gate", **machine_env(home, tmp))
    assert "PathTest.case0" in r.out, r.out + r.err
    record = newest_run(proj)
    written = {f["id"]: f["message"] for f in record["failing"]}
    latest = {f["id"]: f["message"] for f in proj.read_json(".sprint/latest.json")["failing"]}
    out = [written[f"PathTest.case{i}"] for i in range(len(messages))]
    assert out == [latest[f"PathTest.case{i}"] for i in range(len(messages))]
    return out


# --------------------------------------------------------------------------- AC1


def test_S09_project_paths_are_written_relative_to_the_root(proj, home, tmp):
    root = proj.root
    msgs = gate(
        proj,
        home,
        tmp,
        [
            f"{root}{SEP}src{SEP}app.py:3: AssertionError",
            f"at render ({root.as_uri()}/src/app.py:3:7)",
            f"project root {root}",
            "source ~/Desktop/proj/.sprint/baseline.json",
            f"{root.as_posix()}/lib/util.py failed",
            f"not this one: {root}-old{SEP}x.py",
        ],
    )
    assert msgs[0] == f"src{SEP}app.py:3: AssertionError"
    assert msgs[1] == "at render (src/app.py:3:7)"
    assert msgs[2] == "project root ."
    assert msgs[3] == "source .sprint/baseline.json"
    assert msgs[4] == "lib/util.py failed"
    # a sibling folder whose name starts like the project's is not the project
    assert not msgs[5].startswith("not this one: .")
    assert msgs[5] == f"not this one: ~{SEP}Desktop{SEP}proj-old{SEP}x.py"


# --------------------------------------------------------------------------- AC2


def test_S09_home_temp_folders_become_tilde_and_tmpdir(proj, home, tmp):
    real = os.path.realpath(tmp)
    messages = [
        f"cannot read {home}{SEP}notes{SEP}todo.txt",
        f"wrote {tmp}{SEP}build-1234{SEP}out.log",
        "lock held: /tmp/s09.lock and /var/tmp/s09.cache",
        f"real path {real}{SEP}x",
        f"home {home}",
    ]
    if real.startswith("/private/"):  # macOS: /var and /tmp are links into /private
        messages += [f"unresolved {real[len('/private') :]}/y", "/private/tmp/s09.sock"]
    msgs = gate(proj, home, tmp, messages)
    assert msgs[0] == f"cannot read ~{SEP}notes{SEP}todo.txt"
    assert msgs[1] == f"wrote $TMPDIR{SEP}build-1234{SEP}out.log"
    assert msgs[2] == "lock held: $TMPDIR/s09.lock and $TMPDIR/s09.cache"
    assert msgs[3] == f"real path $TMPDIR{SEP}x"
    assert msgs[4] == "home ~"
    if len(msgs) > 5:
        assert msgs[5] == "unresolved $TMPDIR/y"
        assert msgs[6] == "$TMPDIR/s09.sock"


# --------------------------------------------------------------------------- AC3


def test_S09_login_host_and_folder_names_made_from_paths(proj, home, tmp):
    msgs = gate(
        proj,
        home,
        tmp,
        [
            f"/opt/ci/pytest-of-{LOGIN}/pytest-7/test_x0",
            f"pushed by {LOGIN}@{HOST}",
            f"session folder /opt/claude/{encode(str(home))}-Desktop-other/x",
            f"session folder /opt/claude/{encode(str(proj.root))}/x",
            "a plain word stays: the ci server said hello",
        ],
    )
    if HAS_LOGIN:
        assert msgs[0] == "/opt/ci/pytest-of-$USER/pytest-7/test_x0"
        assert msgs[1].startswith("pushed by $USER@")
        assert f"{LOGIN}@" not in msgs[1]
    if HAS_HOST:  # $HOST, or $USER where the host name is the login (as on some Macs)
        assert HOST not in msgs[1] and msgs[1].endswith(("@$HOST", "@$USER")), msgs[1]
    assert msgs[2] == "session folder /opt/claude/~/x"
    assert msgs[3] == "session folder /opt/claude/<project>/x"
    assert msgs[4] == "a plain word stays: the ci server said hello"


# --------------------------------------------------------------------------- AC4


def test_S09_cut_short_paths_are_rewritten_as_far_as_they_go(proj, home, tmp):
    t, root = str(tmp), str(proj.root)
    msgs = gate(
        proj,
        home,
        tmp,
        [
            f"expected '{t[:-5]}…' to include x",
            f"expected '{t[:-5]}...' as well",
            f"expected '/tmp/claude-502/{encode(str(home))[:-3]}…' to contain y",
            f"PATH starts with ...{root[len(root) // 2 :]}{SEP}.venv{SEP}bin",
            f"/opt/ci/pytest-of-{LOGIN[:4]}…",
            "a sentence that just trails off...",
        ],
    )
    assert msgs[0] == "expected '$TMPDIR…' to include x"
    assert msgs[1] == "expected '$TMPDIR...' as well"
    assert msgs[2] == "expected '$TMPDIR/claude-502/~…' to contain y"
    assert msgs[3] == f"PATH starts with …{SEP}.venv{SEP}bin"
    if len(LOGIN) >= 4:
        assert msgs[4] == "/opt/ci/pytest-of-$USER…"
    assert msgs[5] == "a sentence that just trails off..."


# --------------------------------------------------------------------------- AC5

EMIT = r"""
import pathlib, sys
from xml.sax.saxutils import quoteattr as q
root = pathlib.Path(__file__).resolve().parent
home, tmp = sys.argv[1], sys.argv[2]
passed = ["AuthTest.S01_lockoutAfter5Attempts", "InvoiceTest.S02_roundsToPaise",
          "InvoiceTest.S02_pdf", "HealthTest.healthCheck"]
cases = ['<testcase classname=%s name=%s time="0.001"/>' % (q(t.split(".")[0]), q(t.split(".")[1]))
         for t in passed]
cases.append('<testcase classname="AuthTest" name="S01_login" time="0.001"><skipped message=%s/></testcase>'
             % q(tmp + "/skip/reason.txt is missing"))
cases.append('<testcase classname="PathTest" name="every" time="0.001"><failure message=%s>at %s</failure></testcase>'
             % (q(home + "/notes.txt: expected 1"), q(str(root))))
out = root / ".sprint" / "out" / "junit.xml"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('<?xml version="1.0"?><testsuites><testsuite name="emit">%s</testsuite></testsuites>'
               % "".join(cases), encoding="utf-8")
sys.exit(1)
"""


def test_S09_every_string_written_is_covered_and_the_terminal_keeps_the_paths(proj, home, tmp):
    root = proj.root
    emit = root / "emit.py"
    emit.write_text(EMIT, encoding="utf-8")
    proj.config_set("test", "command", f'"{sys.executable}" "{emit}" "{home}" "{tmp}"')
    proj.commit("emit")
    r = proj.sprint("gate", **machine_env(home, tmp))
    assert "PathTest.every" in r.out, r.out + r.err

    record = newest_run(proj)
    latest = proj.read_json(".sprint/latest.json")
    failing = {f["id"]: f for f in record["failing"]}
    skips = {s["id"]: s for s in record["new_skips"]}

    # each kind of string, as written
    assert failing["PathTest.every"]["message"] == "~/notes.txt: expected 1"
    assert failing["PathTest.every"]["file"] == ".sprint/out/junit.xml"
    assert skips["AuthTest.S01_login"]["message"] == "$TMPDIR/skip/reason.txt is missing"
    command = record["runner"][0]["command"]
    assert command.endswith('"emit.py" "~" "$TMPDIR"'), command
    source = record["baseline"]["source"]
    assert ".sprint/baseline.json" in source and not os.path.isabs(source), source

    # nothing anywhere names this machine
    marks = {
        str(root),
        root.as_posix(),
        str(home),
        home.as_posix(),
        str(tmp),
        tmp.as_posix(),
        os.path.realpath(tmp),
        encode(str(home)),
    }
    if HAS_LOGIN:
        marks |= {f"{LOGIN}@", f"pytest-of-{LOGIN}", f"/{LOGIN}/", f"{SEP}{LOGIN}{SEP}"}
    if HAS_HOST:
        marks |= {f"@{HOST}"}
    for written in (record, latest):
        leaks = sorted({m for s in strings(written) for m in marks if m in s})
        assert not leaks, leaks

    # test and run IDs are kept as they are
    assert set(failing) == {"PathTest.every"} and "AuthTest.S01_login" in skips
    assert record["id"] == record["_file"]
    # the terminal report still shows the full paths
    assert str(home) in r.out
