"""Optional Claude Code PreToolUse guard: an early warning, not the enforcement.

Flags edits that remove test functions or add skip/focus markers in test files,
edits to ``.sprint/`` state, and shell commands that delete test files or run
human-only sprintwarden commands. ``pretool_mode = "warn"`` (default) tells
Claude and the human; ``"block"`` denies the tool call. Edits to the ratchet's
own files (baseline, removals, skips, config) always ask the human, and
``--i-am-human`` from an agent always asks or is denied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sprintwarden.config import Config, find_root, load_config
from sprintwarden.hooks._io import emit_json, payload_cwd, read_payload
from sprintwarden.util import SprintError, read_text

TEST_DEFS = [
    r"@(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b",  # JUnit 5 / swift-testing
    r"^\s*(?:async\s+)?def\s+test\w*\s*\(",  # pytest / unittest
    r"\b(?:it|test)(?:\.each\s*\(.*?\)\s*)?\s*\(\s*['\"`]",  # jest / vitest / mocha
    r"^\s*func\s+Test\w*\s*\(",  # Go
    r"#\[(?:\w+::)?test\b",  # Rust #[test], #[tokio::test]
    r"^\s*(?:override\s+)?func\s+test\w*\s*\(",  # XCTest
    r"\[(?:Fact|Theory|Test|TestMethod|TestCase)\b",  # .NET
]
SKIP_MARKERS = [
    (r"@Disabled\b", "@Disabled"),
    (r"@Ignore\b", "@Ignore"),
    (r"@pytest\.mark\.(?:skip|skipif|xfail)\b", "pytest.mark.skip"),
    (r"\bpytest\.skip\s*\(", "pytest.skip("),
    (r"@unittest\.skip", "unittest.skip"),
    (r"\bself\.skipTest\s*\(", "skipTest("),
    (r"\.skip(?:If)?\s*\(", ".skip("),
    (r"\bx(?:it|test|describe)\s*\(", "xit("),
    (r"\.only\s*\(", ".only( (hides every other test)"),
    (r"\bf(?:it|describe)\s*\(", "fit( (hides every other test)"),
    (r"\.todo\s*\(", ".todo("),
    (r"\bt\.Skip(?:f|Now)?\s*\(", "t.Skip("),
    (r"#\[ignore\b", "#[ignore]"),
    (r"\bXCTSkip\b", "XCTSkip"),
    (r"\bSkip\s*=\s*\"", 'Skip = "..."'),
    (r"\[Ignore\b", "[Ignore]"),
]
_TEST_DEF_RX = [re.compile(p, re.M) for p in TEST_DEFS]
_SKIP_RX = [(re.compile(p, re.M), label) for p, label in SKIP_MARKERS]

TEST_NAME_HINTS = re.compile(
    r"(?i)(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|"
    r"[^/]*Tests?\.(java|kt|kts|scala|groovy|swift|cs|fs)|conftest\.py)$|"
    r"(^|/)(tests?|__tests__|spec|src/test|Tests)/"
)

HUMAN_ONLY = re.compile(r"\bsprint(?:warden)?\s+(close|baseline|accept-removal|allow-skip)\b")
I_AM_HUMAN = re.compile(r"--i-am-human\b")
DELETE_CMD = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:git\s+rm|rm|del|erase|Remove-Item|unlink|git\s+mv|mv)\s+(?P<args>[^;&|]+)"
)
STATE_FILES = ("baseline.json", "removals.json", "skips.json", "config.toml")


@dataclass
class Findings:
    warn: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)


def _count(rxs, text: str) -> int:
    return sum(len(rx.findall(text)) for rx in rxs)


def _skip_markers(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for rx, label in _SKIP_RX:
        n = len(rx.findall(text))
        if n:
            out[label] = n
    return out


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    i, out = 0, []
    p = pattern.replace("\\", "/")
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def is_test_file(rel: str, cfg: Config | None) -> bool:
    rel = rel.replace("\\", "/")
    if cfg and cfg.sources and any(glob_to_regex(g).match(rel) for g in cfg.sources):
        return True
    return bool(TEST_NAME_HINTS.search(rel))


def _rel(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _edit_texts(tool: str, ti: dict[str, Any], path: Path) -> tuple[str, str]:
    if tool == "Write":
        return read_text(path) or "", str(ti.get("content", ""))
    if tool == "MultiEdit":
        edits = ti.get("edits") or []
        old = "\n".join(str(e.get("old_string", "")) for e in edits if isinstance(e, dict))
        new = "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
        return old, new
    if tool == "NotebookEdit":
        return "", str(ti.get("new_source", ""))
    return str(ti.get("old_string", "")), str(ti.get("new_string", ""))


def analyze_edit(tool: str, ti: dict[str, Any], root: Path, cfg: Config | None) -> Findings:
    f = Findings()
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    if not raw:
        return f
    path = Path(raw) if Path(raw).is_absolute() else root / raw
    rel = _rel(path, root)
    if rel is None:
        return f
    if rel.startswith(".sprint/"):
        name = rel.split("/")[-1]
        if rel.startswith(".sprint/sprints/") and tool == "Edit":
            old = str(ti.get("old_string", ""))
            text = read_text(path) or ""
            parts = text.split("+++", 2)
            if len(parts) == 3 and old and old in parts[1]:
                f.ask.append(
                    f"{rel}: this edit changes the sprint's front matter (goal/ACs); agents may only add notes"
                )
            return f
        if rel.startswith(".sprint/sprints/"):
            f.warn.append(f'{rel}: agents may only append notes (use `sprint note "..."`)')
            return f
        if name in STATE_FILES and rel.count("/") == 1:
            f.ask.append(
                f"{rel} is sprintwarden's ratchet state; only humans change it (via the sprint CLI)"
            )
        else:
            f.warn.append(f"{rel} is written by `sprint gate`; don't edit it")
        return f
    if not is_test_file(rel, cfg):
        return f
    old, new = _edit_texts(tool, ti, path)
    lost = _count(_TEST_DEF_RX, old) - _count(_TEST_DEF_RX, new)
    if lost > 0:
        f.warn.append(f"{rel}: this edit removes {lost} test definition(s)")
    before, after = _skip_markers(old), _skip_markers(new)
    added = [label for label, n in after.items() if n > before.get(label, 0)]
    if added:
        f.warn.append(f"{rel}: this edit adds {', '.join(added)}")
    return f


def analyze_bash(command: str, root: Path, cfg: Config | None) -> Findings:
    f = Findings()
    if I_AM_HUMAN.search(command):
        f.ask.append("the command passes --i-am-human: only a human may do that")
    m = HUMAN_ONLY.search(command)
    if m:
        f.ask.append(f"`sprint {m.group(1)}` is human-only; ask the human to run it")
    for dm in DELETE_CMD.finditer(command):
        for arg in dm.group("args").split():
            arg = arg.strip("'\"")
            if arg.startswith("-"):
                continue
            if (
                is_test_file(arg.lstrip("./"), cfg)
                or ".sprint/" in arg
                or arg.rstrip("/") in ("tests", "test", ".sprint")
            ):
                f.warn.append(
                    f"`{dm.group(0).strip()}` deletes or moves test/ratchet files ({arg})"
                )
                break
    if re.search(
        r"(>|\btee\b|sed\s+-i|truncate)\s*[^|;&]*\.sprint/(baseline|removals|skips)\.json", command
    ):
        f.ask.append("the command writes to .sprint/ ratchet state directly")
    return f


def run_hook(cwd: Path) -> int:
    data, _ = read_payload()
    root = find_root(payload_cwd(data, cwd, "CLAUDE_PROJECT_DIR"))
    if root is None:
        return 0
    try:
        cfg = load_config(root)
    except SprintError:
        cfg = None
    if cfg is not None and not cfg.claude_pretool_guard:
        return 0
    tool = str(data.get("tool_name") or "")
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if tool == "Bash":
        findings = analyze_bash(str(ti.get("command", "")), root, cfg)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        findings = analyze_edit(tool, ti, root, cfg)
    else:
        return 0
    if not findings.warn and not findings.ask:
        return 0
    block = cfg is not None and cfg.pretool_mode == "block"
    lines = findings.ask + findings.warn
    msg = (
        "sprintwarden guard: "
        + "; ".join(lines)
        + (
            ". Never delete, skip or weaken existing tests; if a test conflicts with the task, stop and ask the human."
        )
    )
    out: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    hso = out["hookSpecificOutput"]
    if block:
        hso["permissionDecision"] = "deny"
        hso["permissionDecisionReason"] = msg
    elif findings.ask:
        hso["permissionDecision"] = "ask"
        hso["permissionDecisionReason"] = msg
    else:
        hso["additionalContext"] = msg
    out["systemMessage"] = msg
    emit_json(out)
    return 0
