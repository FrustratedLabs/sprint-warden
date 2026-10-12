from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from sprintwarden.attribution import DEFAULT_ID_PATTERN
from sprintwarden.config import find_root, load_config, require_root, set_value
from sprintwarden.globs import find_files
from sprintwarden.stacks import detect_stacks, get_stack, load_stacks
from sprintwarden.util import SprintError, toml_literal, toml_set

SPEC_CONFIG = """[project]
name = "billing-service"
key  = "BILL"                       # short key for the UI
mode = "sprints"                    # "sprints" | "ratchet-only"

[test]
command  = "./gradlew test"         # any shell command, run from repo root
reports  = ["build/test-results/test/*.xml"]
timeout_minutes = 30
clean_reports_before_run = true

[sprint]                            # ignored in ratchet-only mode
current = "S03"
id_pattern = '(?i)\\bS(\\d{2,})(?:[_\\]\\s:-]|$)'   # group 1 = sprint number

[gate]
fail_on_new_skips = true
fail_on_missing_tests = true
require_current_sprint_tests = true

[hooks]
claude_stop_hook = true
git_pre_push = true

[ui]
allure_url = ""                     # optional: link out for per-test history
"""


def project(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".sprint").mkdir(exist_ok=True)
    (tmp_path / ".sprint" / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_S01_loads_the_spec_config(tmp_path):
    cfg = load_config(project(tmp_path, SPEC_CONFIG))
    assert (cfg.name, cfg.key, cfg.mode) == ("billing-service", "BILL", "sprints")
    assert cfg.sprint_current == "S03"
    (suite,) = cfg.suites
    assert suite.command == "./gradlew test" and suite.reports == ["build/test-results/test/*.xml"]
    assert suite.timeout_minutes == 30
    assert cfg.clean_reports_before_run and cfg.fail_on_new_skips and cfg.git_pre_push
    assert cfg.id_pattern.startswith("(?i)\\bS")
    assert cfg.warnings == []


def test_S01_defaults_for_minimal_config(tmp_path):
    cfg = load_config(
        project(
            tmp_path,
            '[project]\nmode = "ratchet-only"\n[test]\ncommand = "make test"\nreports = "out/*.xml"\n',
        )
    )
    assert cfg.name == tmp_path.name and cfg.key
    assert cfg.suites[0].reports == ["out/*.xml"]
    assert cfg.id_pattern == DEFAULT_ID_PATTERN
    assert cfg.history_in_git and cfg.history_keep == 0
    assert cfg.claude_session_start and not cfg.claude_pretool_guard
    assert cfg.stop_hook_max_blocks == 3 and cfg.sprint_current == ""


def test_S01_multiple_suites(tmp_path):
    cfg = load_config(
        project(
            tmp_path,
            """[project]
name = "mono"
[test]
timeout_minutes = 5
[[test.suites]]
name = "api"
command = "./gradlew test"
reports = ["api/**/build/test-results/**/*.xml"]
[[test.suites]]
name = "web"
cwd = "web"
command = "npx vitest run"
reports = [".sprint/out/web.xml"]
timeout_minutes = 2
env = { CI = "1" }
""",
        )
    )
    assert [s.name for s in cfg.suites] == ["api", "web"]
    assert cfg.suites[0].timeout_minutes == 5 and cfg.suites[1].timeout_minutes == 2
    assert cfg.suites[1].cwd == "web" and cfg.suites[1].env == {"CI": "1"}
    assert cfg.report_globs == ["api/**/build/test-results/**/*.xml", ".sprint/out/web.xml"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[project]\nmode = 'kanban'\n[test]\ncommand='x'\nreports=['a']", "project.mode"),
        ("[project]\nname='x'", "no test command"),
        ("[test]\ncommand=''\nreports=['a']", "empty command"),
        ("[test]\ncommand='x'", "no report globs"),
        ("[test]\ncommand='x'\nreports=['/abs/*.xml']", "relative"),
        ("[test]\ncommand='x'\nreports=['../up/*.xml']", "relative"),
        ("[test]\ncommand='x'\nreports=['a']\n[sprint]\nid_pattern='S(\\d+'", "valid regex"),
        ("[test]\ncommand='x'\nreports=['a']\n[sprint]\nid_pattern='S\\d+'", "capture group"),
        ("[test]\ncommand='x'\nreports=['a']\n[sprint]\ncurrent='sprint3'", "invalid sprint id"),
        ("[test]\ncommand='x'\nreports=['a']\n[gate]\nfail_on_new_skips='yes'", "true or false"),
        ("[test]\ncommand='x'\nreports=['a']\ntimeout_minutes=-1", "non-negative"),
        ("[test]\ncommand='x'\nreports=['a']\n[hooks]\npretool_mode='nag'", "pretool_mode"),
        ("[test\ncommand='x'", "invalid TOML"),
    ],
)
def test_S01_invalid_configs(tmp_path, text, message):
    with pytest.raises(SprintError, match=message):
        load_config(project(tmp_path, text))


def test_S01_unknown_keys_are_warnings(tmp_path):
    cfg = load_config(
        project(tmp_path, "[test]\ncommand='x'\nreports=['a']\ncomand='typo'\n[extra]\na=1\n")
    )
    assert "unknown key test.comand" in cfg.warnings and "unknown section [extra]" in cfg.warnings


def test_S01_find_root_walks_up(tmp_path):
    root = project(tmp_path, SPEC_CONFIG)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_root(deep) == root.resolve()
    assert find_root(tmp_path.parent) is None or find_root(tmp_path.parent) != root.resolve()
    with pytest.raises(SprintError):
        require_root(tmp_path.parent / "definitely-not-a-project-xyz")


def test_S01_set_value_edits_in_place(tmp_path):
    root = project(tmp_path, SPEC_CONFIG)
    set_value(root, "sprint", "current", "S04")
    set_value(root, "history", "keep", 500)
    set_value(root, "project", "stack", "gradle")
    text = (root / ".sprint" / "config.toml").read_text()
    data = tomllib.loads(text)
    assert data["sprint"]["current"] == "S04"
    assert data["history"]["keep"] == 500
    assert data["project"]["stack"] == "gradle"
    assert "# short key for the UI" in text and "# group 1 = sprint number" in text
    assert data["sprint"]["id_pattern"] == tomllib.loads(SPEC_CONFIG)["sprint"]["id_pattern"]


def test_S01_toml_set_ignores_array_tables_with_same_name():
    text = "[[test.suites]]\nname='a'\n[test]\ncommand='x'\n"
    out = toml_set(text, "test", "command", "y")
    assert tomllib.loads(out)["test"]["command"] == "y"
    assert tomllib.loads(out)["test"]["suites"][0]["name"] == "a"


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        'quote " inside',
        "back\\slash",
        "both \\ and '",
        "new\nline",
        "tab\t",
        True,
        3,
        2.5,
        ["a", "b"],
        [],
        {"K": "v"},
    ],
)
def test_S01_toml_literal_round_trips(value):
    assert tomllib.loads(f"v = {toml_literal(value)}")["v"] == value


def test_S01_builtin_stack_templates_are_complete():
    stacks = load_stacks()
    expected = {
        "gradle",
        "maven",
        "pytest",
        "vitest",
        "jest",
        "go",
        "swift",
        "cargo",
        "dotnet",
        "custom",
    }
    assert expected <= set(stacks)
    for name, s in stacks.items():
        if name == "custom":
            continue
        assert s.command and s.reports and s.detect, name
    assert get_stack("pytest").reports == [".sprint/out/junit.xml"]
    assert get_stack("jest").env == {"JEST_JUNIT_OUTPUT_DIR": ".sprint/out"}
    with pytest.raises(SprintError, match="unknown stack"):
        get_stack("cobol")


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"build.gradle.kts": ""}, "gradle"),
        ({"pom.xml": "<project/>"}, "maven"),
        ({"pyproject.toml": "[tool.pytest.ini_options]\n"}, "pytest"),
        ({"conftest.py": ""}, "pytest"),
        ({"package.json": '{"devDependencies": {"vitest": "^3"}}'}, "vitest"),
        (
            {
                "package.json": '{"devDependencies": {"vitest": "^3", "@testing-library/jest-dom": "1"}}'
            },
            "vitest",
        ),
        ({"package.json": '{"devDependencies": {"jest": "^30"}}'}, "jest"),
        ({"go.mod": "module x"}, "go"),
        ({"Package.swift": ""}, "swift"),
        ({"Cargo.toml": ""}, "cargo"),
        ({"App.csproj": ""}, "dotnet"),
        ({"build.gradle": "", "package.json": '{"vitest": 1}'}, "gradle"),
    ],
)
def test_S01_detect_stacks(tmp_path, files, expected):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    found = detect_stacks(tmp_path)
    assert found and found[0].name == expected


def test_S01_detect_nothing(tmp_path):
    (tmp_path / "README.md").write_text("hi")
    assert detect_stacks(tmp_path) == []


def test_S01_user_stack_templates_override(tmp_path, _isolated_home):
    (_isolated_home / "stacks").mkdir()
    (_isolated_home / "stacks" / "bazel.toml").write_text(
        'name = "bazel"\npriority = 70\n[[detect]]\nfile = "MODULE.bazel"\n'
        '[test]\ncommand = "bazel test //..."\nreports = ["bazel-testlogs/**/test.xml"]\n'
    )
    (tmp_path / "MODULE.bazel").write_text("")
    assert detect_stacks(tmp_path)[0].name == "bazel"


def test_S01_find_files_globs(tmp_path):
    def touch(rel):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")

    for rel in [
        "build/test-results/test/TEST-a.xml",
        "mod/build/test-results/test/TEST-b.xml",
        "mod/sub/build/test-results/integ/TEST-c.xml",
        "node_modules/pkg/build/test-results/test/TEST-junk.xml",
        "explicit/node_modules/r.xml",
        ".sprint/out/junit.xml",
        "target/surefire-reports/TEST-d.xml",
        "target/surefire-reports/d.txt",
    ]:
        touch(rel)
    rel = lambda ps: [p.relative_to(tmp_path).as_posix() for p in ps]  # noqa: E731
    assert rel(find_files(tmp_path, ["**/build/test-results/**/*.xml"])) == [
        "build/test-results/test/TEST-a.xml",
        "mod/build/test-results/test/TEST-b.xml",
        "mod/sub/build/test-results/integ/TEST-c.xml",
    ]
    assert rel(find_files(tmp_path, ["build/test-results/test/*.xml"])) == [
        "build/test-results/test/TEST-a.xml"
    ]
    assert rel(find_files(tmp_path, ["explicit/node_modules/*.xml"])) == [
        "explicit/node_modules/r.xml"
    ]
    assert rel(find_files(tmp_path, [".sprint/out/junit.xml", "./.sprint/out/junit.xml"])) == [
        ".sprint/out/junit.xml"
    ]
    assert rel(find_files(tmp_path, ["**/target/surefire-reports/*.xml"])) == [
        "target/surefire-reports/TEST-d.xml"
    ]
    assert find_files(tmp_path, ["nope/**/*.xml"]) == []
