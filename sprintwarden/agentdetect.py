"""Best-effort detection of who is running the CLI: a coding agent, CI or a human.

Used for the ``agent`` field of run records and for the human-only guard.
This is a speed bump, not security: any process can fake or unset these
variables. CI and code review are the real authority (see docs/FAQ in README).

Override with ``SPRINT_AGENT=<name>`` (e.g. ``SPRINT_AGENT=human``).
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

HUMAN = "human"
CI = "ci"
UNKNOWN = "unknown"
NON_AGENTS = {HUMAN, CI, UNKNOWN}

_FALSY = {"", "0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}

# (agent name, [(env var, required value or None for "set and truthy")]).
# Sources: each agent's docs where documented, otherwise widely used detectors
# (vercel/detect-agent, the Hugging Face agent-harness registry, is-ai-agent).
_MARKERS: list[tuple[str, list[tuple[str, str | None]]]] = [
    (
        "claude-code",
        [("CLAUDECODE", "1"), ("CLAUDE_CODE_CHILD_SESSION", None), ("CLAUDE_CODE_ENTRYPOINT", None)],
    ),
    (
        "cursor",
        [("CURSOR_AGENT", None), ("CURSOR_SANDBOX", None), ("CURSOR_EXTENSION_HOST_ROLE", "agent-exec")],
    ),
    (
        "codex",
        [
            ("CODEX_SANDBOX", None),
            ("CODEX_SANDBOX_NETWORK_DISABLED", None),
            ("CODEX_CI", None),
            ("CODEX_THREAD_ID", None),
        ],
    ),
    ("gemini-cli", [("GEMINI_CLI", None)]),
    ("antigravity", [("ANTIGRAVITY_AGENT", None), ("ANTIGRAVITY_TRAJECTORY_ID", None)]),
    (
        "copilot",
        [("COPILOT_CLI", None), ("COPILOT_AGENT_SESSION_ID", None), ("COPILOT_AGENT_JOB_ID", None)],
    ),
    ("vscode-agent", [("VSCODE_AGENT", None)]),
    ("cline", [("CLINE_ACTIVE", None), ("CLINE_TASK_ID", None)]),
    ("opencode", [("OPENCODE", None)]),
    ("amp", [("AMP_CURRENT_THREAD_ID", None)]),
    ("goose", [("GOOSE_TERMINAL", None)]),
    ("kiro", [("KIRO_SESSION_ID", None)]),
    ("augment", [("AUGMENT_AGENT", None)]),
    ("roo", [("ROO_CODE_TASK_ID", None)]),
    ("kilo", [("KILOCODE_FEATURE", None)]),
    ("crush", [("CRUSH", None)]),
    ("trae", [("TRAE_AI_SHELL_ID", None)]),
    ("qwen-code", [("QWEN_CODE", None)]),
]

_CI_VARS = (
    "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "BUILDKITE", "TF_BUILD",
    "BITBUCKET_COMMIT", "TEAMCITY_VERSION", "CODEBUILD_BUILD_ARN", "DRONE", "JENKINS_URL",
)


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in _FALSY


def _agent_from_convention(value: str) -> str | None:
    """Parse ``AI_AGENT``/``AGENT`` values like ``claude-code_2-1-296_agent`` or ``goose@1.2``."""
    value = value.strip()
    if value.lower() in _FALSY:
        return None
    if value.lower() in _TRUTHY:
        return "agent"
    m = re.match(r"[A-Za-z][A-Za-z0-9-]*", value)
    return m.group(0).lower() if m else "agent"


def detect(env: Mapping[str, str] | None = None, *, stdin_tty: bool | None = None) -> str:
    env = os.environ if env is None else env
    override = env.get("SPRINT_AGENT", "").strip()
    if override:
        return override.lower()
    conv = env.get("AI_AGENT")
    if conv:
        name = _agent_from_convention(conv)
        if name:
            return name
    for name, markers in _MARKERS:
        for var, required in markers:
            value = env.get(var)
            if value is None:
                continue
            if required is None and _truthy(value):
                return name
            if required is not None and value.strip() == required:
                return name
    if Path("/opt/.devin").exists():
        return "devin"
    legacy = env.get("AGENT")
    if legacy:
        name = _agent_from_convention(legacy)
        if name:
            return name
    if _truthy(env.get("CI")) or any(env.get(v) for v in _CI_VARS):
        return CI
    if stdin_tty is None:
        try:
            stdin_tty = sys.stdin is not None and sys.stdin.isatty()
        except (ValueError, OSError):
            stdin_tty = False
    return HUMAN if stdin_tty else UNKNOWN


def is_agent(name: str) -> bool:
    return name not in NON_AGENTS
