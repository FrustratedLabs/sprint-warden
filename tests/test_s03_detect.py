from __future__ import annotations

import pytest

from sprintwarden.agentdetect import detect, is_agent


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"SPRINT_AGENT": "Human", "CLAUDECODE": "1"}, "human"),
        ({"CLAUDECODE": "1"}, "claude-code"),
        ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, "claude-code"),
        ({"AI_AGENT": "claude-code_2-1-296_agent"}, "claude-code"),
        ({"AI_AGENT": "goose@1.9"}, "goose"),
        ({"AI_AGENT": "1"}, "agent"),
        ({"AI_AGENT": "0", "CI": "true"}, "ci"),
        ({"CURSOR_AGENT": "1"}, "cursor"),
        ({"CURSOR_TRACE_ID": "abc"}, "unknown"),  # human Cursor terminals have this too
        ({"CODEX_SANDBOX": "seatbelt"}, "codex"),
        ({"CODEX_CI": "1"}, "codex"),
        ({"GEMINI_CLI": "1"}, "gemini-cli"),
        ({"COPILOT_AGENT_JOB_ID": "x", "GITHUB_ACTIONS": "true", "CI": "true"}, "copilot"),
        ({"OPENCODE": "1"}, "opencode"),
        ({"CLINE_ACTIVE": "true"}, "cline"),
        ({"AGENT": "amp"}, "amp"),
        ({"AGENT": "false"}, "unknown"),
        ({"CI": "true"}, "ci"),
        ({"CI": "woodpecker"}, "ci"),
        ({"CI": "false"}, "unknown"),
        ({"GITLAB_CI": "true"}, "ci"),
        ({"CLAUDECODE": "0"}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_S03_detect_agents_ci_and_overrides(env, expected, monkeypatch, tmp_path):
    monkeypatch.setattr("sprintwarden.agentdetect.Path", lambda p: tmp_path / "no-devin")
    assert detect(env, stdin_tty=False) == expected


def test_S03_detect_human_on_a_terminal():
    assert detect({}, stdin_tty=True) == "human"
    assert detect({"CI": "1"}, stdin_tty=True) == "ci"


def test_S03_detect_is_agent():
    assert is_agent("claude-code") and is_agent("agent") and is_agent("codex")
    assert not is_agent("human") and not is_agent("ci") and not is_agent("unknown")
