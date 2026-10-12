"""Phase 3: enforcement integrations (Stop hook, pre-push, guard, SessionStart,
MCP, other agents' stop hooks, installers)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from sprintwarden.hooks.claude_pretool import (
    analyze_bash,
    analyze_edit,
    glob_to_regex,
    is_test_file,
)
from sprintwarden.mcp import Server
from tests.helpers import BASE_TESTS, FakeProject, T

pytestmark = pytest.mark.slow


@pytest.fixture
def proj(tmp_path, _isolated_home) -> FakeProject:
    p = FakeProject(tmp_path / "repo", _isolated_home)
    r = p.init("--ratchet-only")
    assert r.code == 0, r.out + r.err
    p.commit("add sprintwarden")
    return p


_attempt = iter(range(10_000))


def stop(p: FakeProject, active: bool = False, session: str = "s1", **extra):
    payload = {
        "session_id": session,
        "hook_event_name": "Stop",
        "stop_hook_active": active,
        "cwd": str(p.root),
        "last_assistant_message": f"done (attempt {next(_attempt)})",
    }
    return p.sprint("gate", "--hook", stdin=json.dumps(payload), agent="claude-code", **extra)


def run_files(p: FakeProject) -> int:
    return len(list((p.root / ".sprint" / "runs").rglob("*.json")))


def break_one(p: FakeProject, message: str = "expected 423 but was 200") -> None:
    tests = [dict(t) for t in BASE_TESTS]
    tests[1] = T("AuthTest", "S01_lockoutAfter5Attempts", "failed", message)
    p.scenario(tests)


# --------------------------------------------------------------------------- Stop hook


def test_S03_stop_hook_allows_on_pass_and_skips_when_nothing_changed(proj):
    r = stop(proj)
    assert r.code == 0, r.err
    n = run_files(proj)
    r = stop(proj)
    assert r.code == 0 and run_files(proj) == n, "unchanged tree: no new gate run"


def test_S03_stop_hook_blocks_with_an_agent_actionable_report(proj):
    break_one(proj)
    proj.scenario(
        [
            t
            for t in json.loads((proj.root / "scenario.json").read_text())["tests"]
            if t["name"] != "healthCheck"
        ]
    )
    r = stop(proj)
    assert r.code == 2
    assert "REGRESSIONS" in r.err and "[S01] AuthTest.S01_lockoutAfter5Attempts" in r.err
    assert "expected 423 but was 200" in r.err
    assert "MISSING vs baseline" in r.err and "HealthTest.healthCheck" in r.err
    assert "do not delete, skip, rename or weaken tests" in r.err
    latest = proj.read_json(".sprint/latest.json")
    assert latest["trigger"] == "hook:claude-stop" and latest["agent"] == "claude-code"


def test_S03_stop_hook_replays_a_failure_without_rerunning(proj):
    break_one(proj)
    assert stop(proj).code == 2
    n = run_files(proj)
    r = stop(proj, active=True)
    assert r.code == 2 and "Nothing changed since this gate run" in r.err
    assert run_files(proj) == n


def test_S03_stop_hook_loop_guard_lets_go_after_three_blocks(proj):
    break_one(proj)
    assert stop(proj, active=False).code == 2  # 1
    assert stop(proj, active=True).code == 2  # 2
    assert stop(proj, active=True).code == 2  # 3
    r = stop(proj, active=True)  # 4th attempt in the same chain: let go, tell the human
    assert r.code == 0
    assert "still failing after 3 attempts" in json.loads(r.out)["systemMessage"]
    # a new user turn blocks again
    assert stop(proj, active=False).code == 2
    # other sessions are independent
    assert stop(proj, active=True, session="other").code == 2


def test_S03_stop_hook_counts_a_duplicate_invocation_once(proj):
    break_one(proj)
    payload = {
        "session_id": "dup",
        "stop_hook_active": True,
        "cwd": str(proj.root),
        "last_assistant_message": "done!",
    }
    for _ in range(4):  # the same event delivered 4 times (e.g. settings + plugin)
        assert (
            proj.sprint("gate", "--hook", stdin=json.dumps(payload), agent="claude-code").code == 2
        )
    state = proj.read_json(".sprint/out/hook-state.json")
    assert state["sessions"]["dup"]["blocks"] == 1


def test_S03_stop_hook_notices_a_second_edit_to_a_modified_file(proj):
    break_one(proj)  # scenario.json is now " M"
    assert stop(proj).code == 2
    proj.scenario(BASE_TESTS)  # edited again: porcelain status line is identical
    r = stop(proj, active=True)
    assert r.code == 0, "fingerprint changed, so the gate re-ran and passed"


def test_S03_stop_hook_respects_config_and_skip(proj):
    break_one(proj)
    assert stop(proj, SPRINT_SKIP="1").code == 0
    proj.config_set("hooks", "claude_stop_hook", False)
    assert stop(proj).code == 0


def test_S03_stop_hook_blocks_on_a_broken_config(proj):
    (proj.root / ".sprint" / "config.toml").write_text("[test\n")
    r = stop(proj)
    assert r.code == 2 and "config.toml is invalid" in r.err


def test_S03_stop_hook_outside_a_project_is_silent(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "plain", _isolated_home, git=False)
    r = p.sprint("gate", "--hook", stdin=json.dumps({"cwd": str(p.root)}))
    assert r.code == 0 and r.out == "" and r.err == ""


def test_S03_stop_hook_tolerates_empty_stdin(proj):
    r = proj.sprint("gate", "--hook", stdin="")
    assert r.code == 0


# --------------------------------------------------------------------------- settings / installers


def test_S03_init_merges_claude_settings_without_clobbering(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "r", _isolated_home)
    settings = p.root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls)"]},
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]
                },
            }
        )
    )
    assert p.init("--ratchet-only", "--with-guard").code == 0
    data = json.loads(settings.read_text())
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    stop_cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert stop_cmds == ["notify-send done", "sprint gate --hook"]
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "sprint hook session-start"
    assert data["hooks"]["PreToolUse"][0]["matcher"].startswith("Edit|Write")
    assert "claude_pretool_guard = true" in (p.root / ".sprint" / "config.toml").read_text()
    before = settings.read_text()
    assert p.sprint("init", "--ratchet-only", "--yes").code == 0
    assert settings.read_text() == before, "idempotent"


def test_S03_init_refuses_to_touch_invalid_settings(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "r", _isolated_home)
    settings = p.root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{ not json")
    r = p.init("--ratchet-only")
    assert r.code == 2 and "invalid JSON" in r.err
    assert settings.read_text() == "{ not json"


def test_S03_other_agent_hook_installers(proj):
    r = proj.sprint(
        "install-hooks",
        "--agent",
        "cursor",
        "--agent",
        "codex",
        "--agent",
        "gemini",
        "--agent",
        "copilot",
    )
    assert r.code == 0, r.err
    cursor = proj.read_json(".cursor/hooks.json")
    assert (
        cursor["version"] == 1
        and cursor["hooks"]["stop"][0]["command"] == "sprint hook cursor-stop"
    )
    codex = proj.read_json(".codex/hooks.json")
    assert codex["hooks"]["Stop"][0]["hooks"][0]["command"] == "sprint hook codex-stop"
    gemini = proj.read_json(".gemini/settings.json")
    assert gemini["context"]["fileName"][0] == "AGENTS.md"
    assert gemini["hooks"]["AfterAgent"][0]["hooks"][0]["timeout"] == 1800000
    copilot = proj.read_json(".github/hooks/sprintwarden.json")
    assert copilot["hooks"]["agentStop"][0]["bash"] == "sprint hook copilot-agent-stop"
    r = proj.sprint("install-hooks", "--agent", "cursor")
    assert "already" in r.out


@pytest.mark.parametrize(
    ("hook", "payload", "blocked", "allowed"),
    [
        (
            "cursor-stop",
            {"status": "completed", "loop_count": 0, "conversation_id": "c"},
            lambda o: "followup_message" in o,
            lambda o: o == {},
        ),
        (
            "codex-stop",
            {"session_id": "x", "stop_hook_active": False},
            lambda o: o["decision"] == "block",
            lambda o: o == {},
        ),
        (
            "gemini-after-agent",
            {"session_id": "g", "stop_hook_active": False},
            lambda o: o["decision"] == "deny",
            lambda o: o == {},
        ),
        (
            "copilot-agent-stop",
            {"stop_hook_active": False},
            lambda o: o["decision"] == "block",
            lambda o: o == {"decision": "allow"},
        ),
    ],
)
def test_S03_other_agent_stop_hooks_speak_their_protocol(proj, hook, payload, blocked, allowed):
    payload = {**payload, "cwd": str(proj.root)}
    r = proj.sprint("hook", hook, stdin=json.dumps(payload), agent="other")
    assert r.code == 0 and allowed(json.loads(r.out)), r.out + r.err
    break_one(proj)
    r = proj.sprint("hook", hook, stdin=json.dumps(payload), agent="other")
    out = json.loads(r.out)
    assert r.code == 0 and blocked(out), r.out
    reason = out.get("followup_message") or out.get("reason")
    assert "REGRESSIONS" in reason


def test_S03_other_agent_cursor_ignores_aborted_turns(proj):
    break_one(proj)
    r = proj.sprint(
        "hook", "cursor-stop", stdin=json.dumps({"status": "aborted", "cwd": str(proj.root)})
    )
    assert json.loads(r.out) == {}


# --------------------------------------------------------------------------- pre-push


@pytest.fixture
def pushable(tmp_path, _isolated_home):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    p = FakeProject(tmp_path / "repo", _isolated_home)
    hooks = p.root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "chained-ran.txt"  # outside the repo: it must not dirty the tree
    existing = hooks / "pre-push"
    existing.write_text(
        f'#!/bin/sh\necho chained >> "{marker.as_posix()}"\nexit "${{CHAIN_EXIT:-0}}"\n'
    )
    existing.chmod(0o755)
    assert p.init("--ratchet-only").code == 0
    p.commit("add sprintwarden")
    p.git("remote", "add", "origin", str(remote))
    return p, marker


def push(p: FakeProject, **env):
    return subprocess.run(
        ["git", "push", "-q", "origin", "main"],
        cwd=p.root,
        capture_output=True,
        text=True,
        env=p.env("human", **env),
    )


def test_S03_pre_push_installs_and_chains_existing_hook(pushable):
    p, marker = pushable
    hook = (p.root / ".git" / "hooks" / "pre-push").read_text()
    assert "sprintwarden-managed-hook" in hook
    assert (p.root / ".git" / "hooks" / "pre-push.local").exists()
    r = push(p)
    assert r.returncode == 0, r.stderr
    assert marker.read_text().strip() == "chained"
    r = push(p, CHAIN_EXIT="1")
    assert r.returncode != 0, "a failing chained hook still blocks"


def test_S03_pre_push_blocks_on_gate_failure_and_records_bypass(pushable):
    p, _ = pushable
    break_one(p)
    p.commit("oops")
    r = push(p)
    assert r.returncode != 0
    assert "push blocked" in r.stderr and "REGRESSION from sprint S01" in r.stderr
    r = push(p, SPRINT_SKIP="1")
    assert r.returncode == 0, r.stderr
    assert "BYPASSED" in r.stderr
    records = [json.loads(f.read_text()) for f in (p.root / ".sprint" / "runs").rglob("*.json")]
    bypass = [x for x in records if x.get("bypassed")]
    assert (
        len(bypass) == 1
        and bypass[0]["result"] == "bypassed"
        and bypass[0]["trigger"] == "hook:pre-push"
    )


def test_S03_pre_push_reuses_a_passing_gate_for_the_same_tree(pushable):
    p, _ = pushable
    assert p.sprint("gate").code == 0
    n = run_files(p)
    r = push(p)
    assert r.returncode == 0 and "already passed for this exact tree" in r.stderr
    assert run_files(p) == n


def test_S03_pre_push_reinstall_is_idempotent(pushable):
    p, _ = pushable
    r = p.sprint("install-hooks", "--agent", "git")
    assert "already installed" in r.out
    assert not (p.root / ".git" / "hooks" / "pre-push.local.1").exists()


# --------------------------------------------------------------------------- PreToolUse guard


def test_S03_pretool_glob_and_test_file_detection():
    assert glob_to_regex("**/src/test/**").match("mod/src/test/java/A.java")
    assert glob_to_regex("**/test_*.py").match("test_a.py")
    for rel in [
        "tests/test_x.py",
        "pkg/foo_test.go",
        "web/a.test.tsx",
        "src/test/java/FooTest.java",
        "Tests/AppTests/AppTests.swift",
        "conftest.py",
        "x/__tests__/y.js",
        "Foo.Tests/BarTests.cs",
    ]:
        assert is_test_file(rel, None), rel
    for rel in ["src/main/java/Foo.java", "app.py", "README.md", "src/contest.py"]:
        assert not is_test_file(rel, None), rel


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        (
            "def test_a():\n    pass\ndef test_b():\n    pass\n",
            "def test_a():\n    pass\n",
            "removes 1 test definition",
        ),
        (
            "    @Test\n    void a() {}\n",
            "    @Disabled\n    @Test\n    void a() {}\n",
            "@Disabled",
        ),
        ("it('works', () => {})", "it.skip('works', () => {})", ".skip("),
        ("it('works', () => {})", "it.only('works', () => {})", ".only("),
        ("func TestX(t *testing.T) {}", 'func TestX(t *testing.T) { t.Skip("later") }', "t.Skip("),
        ("#[test]\nfn a() {}", "#[test]\n#[ignore]\nfn a() {}", "#[ignore]"),
        ("def test_a(): pass", "@pytest.mark.skip\ndef test_a(): pass", "pytest.mark.skip"),
    ],
)
def test_S03_pretool_flags_removed_and_skipped_tests(tmp_path, old, new, expect):
    f = analyze_edit(
        "Edit",
        {"file_path": str(tmp_path / "tests" / "test_x.py"), "old_string": old, "new_string": new},
        tmp_path,
        None,
    )
    assert any(expect in w for w in f.warn), f


def test_S03_pretool_ignores_ordinary_edits(tmp_path):
    f = analyze_edit(
        "Edit",
        {
            "file_path": str(tmp_path / "src" / "app.py"),
            "old_string": "def test_a(): pass",
            "new_string": "",
        },
        tmp_path,
        None,
    )
    assert not f.warn and not f.ask
    f = analyze_edit(
        "Edit",
        {
            "file_path": str(tmp_path / "tests" / "test_x.py"),
            "old_string": "x = 1",
            "new_string": "x = 2",
        },
        tmp_path,
        None,
    )
    assert not f.warn and not f.ask


def test_S03_pretool_write_compares_with_the_file_on_disk(tmp_path):
    target = tmp_path / "tests" / "test_x.py"
    target.parent.mkdir()
    target.write_text("def test_a(): pass\ndef test_b(): pass\n")
    f = analyze_edit("Write", {"file_path": str(target), "content": "# gone\n"}, tmp_path, None)
    assert any("removes 2" in w for w in f.warn)


def test_S03_pretool_protects_sprint_state(tmp_path):
    (tmp_path / ".sprint" / "sprints").mkdir(parents=True)
    sprint = tmp_path / ".sprint" / "sprints" / "S01-a.md"
    sprint.write_text("+++\nid = 'S01'\ngoal = 'x'\n+++\n## Notes / decisions\n- a\n")
    f = analyze_edit(
        "Write",
        {"file_path": str(tmp_path / ".sprint" / "baseline.json"), "content": "{}"},
        tmp_path,
        None,
    )
    assert f.ask
    f = analyze_edit(
        "Edit",
        {"file_path": str(sprint), "old_string": "goal = 'x'", "new_string": "goal = 'y'"},
        tmp_path,
        None,
    )
    assert f.ask and "front matter" in f.ask[0]
    f = analyze_edit(
        "Edit",
        {"file_path": str(sprint), "old_string": "- a\n", "new_string": "- a\n- b\n"},
        tmp_path,
        None,
    )
    assert not f.ask and not f.warn, "appending notes is fine"


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("rm tests/test_auth.py", "warn"),
        ("git rm -q src/test/java/FooTest.java", "warn"),
        ("rm -rf tests", "warn"),
        ("sprint accept-removal X.y --reason ok", "ask"),
        ("sprint close S03 --i-am-human", "ask"),
        ("echo '{}' > .sprint/baseline.json", "ask"),
        ("sed -i '' 's/a/b/' .sprint/skips.json", "ask"),
        ("ls tests && pytest", None),
        ("rm build/output.txt", None),
        ("sprint gate", None),
    ],
)
def test_S03_pretool_bash_commands(tmp_path, command, kind):
    f = analyze_bash(command, tmp_path, None)
    if kind is None:
        assert not f.warn and not f.ask
    else:
        assert getattr(f, kind), (command, f)


def test_S03_pretool_hook_end_to_end(proj):
    proj.config_set("hooks", "claude_pretool_guard", True)
    payload = {
        "tool_name": "Edit",
        "cwd": str(proj.root),
        "tool_input": {
            "file_path": str(proj.root / "tests" / "test_auth.py"),
            "old_string": "def test_a():\n    pass\n",
            "new_string": "",
        },
    }
    r = proj.sprint("hook", "pretool", stdin=json.dumps(payload), agent="claude-code")
    out = json.loads(r.out)
    assert r.code == 0
    assert "removes 1 test definition" in out["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert out["systemMessage"].startswith("sprintwarden guard")
    proj.config_set("hooks", "pretool_mode", "block")
    out = json.loads(proj.sprint("hook", "pretool", stdin=json.dumps(payload)).out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    proj.config_set("hooks", "claude_pretool_guard", False)
    assert proj.sprint("hook", "pretool", stdin=json.dumps(payload)).out == ""


# --------------------------------------------------------------------------- SessionStart


def test_S03_session_start_briefs_the_agent(tmp_path, _isolated_home):
    p = FakeProject(tmp_path / "s", _isolated_home)
    assert p.init("--sprint-title", "Auth").code in (0, 1)
    r = p.sprint(
        "hook", "session-start", stdin=json.dumps({"source": "compact", "cwd": str(p.root)})
    )
    assert r.code == 0
    assert "[sprintwarden]" in r.out and "Active sprint S01: Auth" in r.out
    assert "sprint gate" in r.out and "human-only" in r.out
    p.config_set("hooks", "claude_session_start", False)
    assert p.sprint("hook", "session-start", stdin="{}").out == ""


# --------------------------------------------------------------------------- MCP


def test_S03_mcp_handshake_and_tools(proj):
    s = Server(proj.root)
    init = s.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "cursor"}},
        }
    )
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "sprintwarden"
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [
        t["name"]
        for t in s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    ]
    assert names == ["sprint_status", "sprint_gate", "sprint_history", "sprint_note"]
    assert not any("close" in n or "baseline" in n or "accept" in n for n in names), (
        "no human-only tools"
    )
    unknown = s.handle({"jsonrpc": "2.0", "id": 3, "method": "server/discover"})
    assert unknown["error"]["code"] == -32601
    bad = s.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "sprint_close"}}
    )
    assert bad["error"]["code"] == -32602
    old = s.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        }
    )
    assert old["result"]["protocolVersion"] == "2025-11-25"


def test_S03_mcp_over_stdio(proj):
    lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "sprint_gate", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "sprint_status", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "sprint_note", "arguments": {"text": "x y z"}},
        },
    ]
    r = proj.sprint("mcp", stdin="\n".join(json.dumps(m) for m in lines) + "\nnot json\n")
    replies = [json.loads(line) for line in r.out.splitlines()]
    assert [m.get("id") for m in replies] == [1, 2, 3, 4, None]
    gate = replies[1]["result"]
    assert gate["isError"] is False and "GATE: PASS" in gate["content"][0]["text"]
    assert "ratchet-only" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["result"]["isError"] is True, "notes need sprints mode"
    assert replies[4]["error"]["code"] == -32700


def test_S03_mcp_gate_failure_is_reported_as_tool_error(proj):
    break_one(proj)
    s = Server(proj.root)
    res = s.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "sprint_gate", "arguments": {}},
        }
    )
    assert res["result"]["isError"] is True and "REGRESSIONS" in res["result"]["content"][0]["text"]


def test_S03_cli_entry_point_runs(proj):
    r = subprocess.run(
        [sys.executable, "-m", "sprintwarden", "--version"], capture_output=True, text=True
    )
    assert r.returncode == 0 and r.stdout.startswith("sprintwarden ")
