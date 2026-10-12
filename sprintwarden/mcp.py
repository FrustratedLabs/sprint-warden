"""A minimal MCP server over stdio (``sprint mcp``), standard library only.

Exposes the agent-safe parts of sprintwarden as tools for any MCP client
(Claude Code, Cursor, Codex, Gemini CLI...). Human-only commands are not
exposed. Protocol: JSON-RPC 2.0, one message per line, ``initialize`` handshake
(2025-11-25 and earlier); unknown methods, including newer-revision discovery
calls, get an immediate ``-32601`` so clients fall back quickly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sprintwarden import __version__

SUPPORTED = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

TOOLS = [
    {
        "name": "sprint_status",
        "description": (
            "Current sprint, its goal and acceptance criteria (with computed state), the last gate "
            "result and the baseline. Call this before starting work."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sprint_gate",
        "description": (
            "Run the full test suite and check the ratchet: no failing tests, no tests missing vs the "
            "baseline, no new skips. Call this before claiming a task is done. Returns pass/fail with "
            "failing, missing and newly skipped tests labelled by sprint."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "no_run": {
                    "type": "boolean",
                    "description": "re-evaluate existing reports instead of running the tests",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sprint_history",
        "description": "Recent gate runs (newest first).",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            "additionalProperties": False,
        },
    },
    {
        "name": "sprint_note",
        "description": "Record a decision in the active sprint's 'Notes / decisions' section, with date and agent name.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 3}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
]


class Server:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.client_agent = "mcp"

    # -- tools
    def _cfg(self):
        from sprintwarden.config import load_config, require_root

        return load_config(require_root(self.cwd))

    def tool_sprint_status(self, _args: dict) -> tuple[str, bool]:
        from sprintwarden.commands import project_status, render_status
        from sprintwarden.report import Style

        status = project_status(self._cfg())
        return render_status(status, Style(color=False)), False

    def tool_sprint_gate(self, args: dict) -> tuple[str, bool]:
        from sprintwarden.gate import run_gate
        from sprintwarden.report import Style, render_agent, render_gate

        result = run_gate(
            self._cfg(), run=not args.get("no_run"), trigger="mcp", agent=self.client_agent
        )
        text = render_gate(result.record, Style(color=False))
        if not result.passed:
            text += "\n\n" + render_agent(result.record)
        return text, not result.passed

    def tool_sprint_history(self, args: dict) -> tuple[str, bool]:
        from sprintwarden import runs
        from sprintwarden.commands import run_summary

        items = [
            run_summary(r) for r in runs.list_runs(self._cfg().paths, int(args.get("limit") or 10))
        ]
        return json.dumps(items, indent=1), False

    def tool_sprint_note(self, args: dict) -> tuple[str, bool]:
        from sprintwarden.lifecycle import add_note

        path = add_note(self._cfg(), str(args.get("text", "")), agent=self.client_agent)
        return f"noted in {path.name}", False

    # -- protocol
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        mid = msg.get("id")
        is_request = "id" in msg
        params = msg.get("params") or {}
        if not is_request:
            return None  # notifications (initialized, cancelled...) get no reply
        if method == "initialize":
            requested = str(params.get("protocolVersion") or "")
            info = params.get("clientInfo") or {}
            if info.get("name"):
                self.client_agent = f"mcp:{info['name']}"
            return self._ok(
                mid,
                {
                    "protocolVersion": requested if requested in SUPPORTED else SUPPORTED[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "sprintwarden", "version": __version__},
                    "instructions": (
                        "sprintwarden guards this repo's tests. Call sprint_status before work and "
                        "sprint_gate before saying you're done. Never delete, skip or weaken tests."
                    ),
                },
            )
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            fn = getattr(self, f"tool_{name}", None) if name in {t["name"] for t in TOOLS} else None
            if fn is None:
                return self._err(mid, -32602, f"unknown tool: {name}")
            try:
                text, is_error = fn(params.get("arguments") or {})
            except Exception as exc:  # report tool failures to the model, not as protocol errors
                text, is_error = f"error: {exc}", True
            return self._ok(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})
        return self._err(mid, -32601, f"method not found: {method}")

    @staticmethod
    def _ok(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, self._err(None, -32700, "parse error"))
                continue
            batch = msg if isinstance(msg, list) else [msg]
            for item in batch:
                if not isinstance(item, dict):
                    continue
                reply = self.handle(item)
                if reply is not None:
                    self._write(stdout, reply)
        return 0

    @staticmethod
    def _write(stdout, data: dict[str, Any]) -> None:
        stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        stdout.flush()


def cmd_mcp(env, args):
    from sprintwarden.commands import Outcome

    return Outcome(Server(env.cwd).serve())
