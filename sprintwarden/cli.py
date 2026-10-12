"""The ``sprint`` command line. Every consumer (agent hooks, git hooks, CI, the
dashboard) calls or reads the same CLI and JSON outputs.

Exit codes: 0 ok, 1 gate failure, 2 config/usage error.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from sprintwarden import __version__
from sprintwarden.commands import Env, HumanOnlyError, Outcome
from sprintwarden.report import Style
from sprintwarden.util import EXIT_USAGE, SprintError, dumps_json

Handler = Callable[[Env, argparse.Namespace], Outcome]


def _lazy(module: str, name: str) -> Handler:
    def call(env: Env, args: argparse.Namespace) -> Outcome:
        import importlib

        return getattr(importlib.import_module(module), name)(env, args)

    return call


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON")
    common.add_argument("-C", dest="directory", default=argparse.SUPPRESS, help="run as if started in DIR")
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="no ANSI colours")
    human = argparse.ArgumentParser(add_help=False)
    human.add_argument(
        "--i-am-human",
        action="store_true",
        help="run a human-only command from an agent's terminal (recorded)",
    )

    p = argparse.ArgumentParser(
        prog="sprint",
        description="sprintwarden: a test ratchet and sprint tracker for AI coding agents.",
        parents=[common],
    )
    p.add_argument("--version", action="version", version=f"sprintwarden {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def cmd(name: str, handler: Handler, help: str, parents=None) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help, parents=[common, *(parents or [])])
        sp.set_defaults(handler=handler)
        return sp

    c = "sprintwarden.commands"
    lc = "sprintwarden.lifecycle"

    sp = cmd("init", _lazy(c, "cmd_init"), "set up .sprint/, agent rules and hooks (idempotent)")
    sp.add_argument("--stack", help="gradle, maven, pytest, vitest, jest, go, swift, cargo, dotnet, custom")
    sp.add_argument("--ratchet-only", action="store_true", help="just the test ratchet, no sprints")
    sp.add_argument("--command", help="test command (overrides the stack template)")
    sp.add_argument("--reports", nargs="+", help="JUnit XML glob(s), relative to the repo root")
    sp.add_argument("--name", help="project name (default: directory name)")
    sp.add_argument("--key", help="short project key for the dashboard")
    sp.add_argument("--sprint-title", help="title of the first sprint (sprints mode)")
    sp.add_argument("--force", action="store_true", help="rewrite config.toml and refresh managed blocks")
    sp.add_argument("--yes", "-y", action="store_true", help="accept the detected stack without asking")
    sp.add_argument("--no-gate", action="store_true", help="don't run the first gate / write the baseline")
    sp.add_argument("--no-hooks", action="store_true", help="don't install Claude Code or git hooks")
    sp.add_argument("--with-guard", action="store_true", help="also install the PreToolUse guard")
    sp.add_argument(
        "--agents",
        help="also install stop hooks for other agents: cursor,codex,gemini,copilot (experimental)",
    )

    sp = cmd("baseline", _lazy(c, "cmd_baseline"), "(human) snapshot the passing suite as the new baseline", [human])
    sp.add_argument("--no-run", action="store_true", help="evaluate existing reports instead of re-running")
    sp.add_argument("--reason", default="", help="note recorded in baseline.json")

    sp = cmd("new", _lazy(lc, "cmd_new"), "create the next sprint file (status planned)")
    sp.add_argument("title", nargs="+")
    sp.add_argument("--goal", default="")

    sp = cmd("start", _lazy(lc, "cmd_start"), "activate a sprint and make it current")
    sp.add_argument("id")

    cmd("status", _lazy(c, "cmd_status"), "current sprint, ACs, last gate, baseline")

    sp = cmd("gate", _lazy(c, "cmd_gate"), "run tests and check the ratchet (exit 1 on failure)")
    sp.add_argument("--hook", action="store_true", help="Claude Code Stop-hook mode (reads hook JSON on stdin)")
    sp.add_argument("--no-run", action="store_true", help="evaluate existing reports without running tests")
    sp.add_argument("-v", "--verbose", action="store_true", help="stream test output to stderr")
    sp.add_argument("--baseline-ref", help="compare against the baseline committed at this git ref (CI)")
    sp.add_argument("--collect-reports", metavar="DIR", help="copy parsed JUnit XML into DIR")
    sp.add_argument("--format", choices=["text", "markdown"], default="text")
    sp.add_argument("--trigger", help=argparse.SUPPRESS)

    sp = cmd("close", _lazy(lc, "cmd_close"), "(human) close the active sprint: baseline, tag, changelog", [human])
    sp.add_argument("id")
    sp.add_argument("--no-run", action="store_true", help="reuse the latest gate run if it matches HEAD")
    sp.add_argument("--no-commit", action="store_true", help="don't commit the closing changes")
    sp.add_argument("--no-tag", action="store_true", help="don't create the sprint-<id> git tag")

    sp = cmd("accept-removal", _lazy(c, "cmd_accept_removal"), "(human) accept that tests were removed", [human])
    sp.add_argument("tests", nargs="*", metavar="test-id", help="test ids, or /regex/")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--all-missing", action="store_true", help="every test missing in the latest gate run")

    sp = cmd("allow-skip", _lazy(c, "cmd_allow_skip"), "(human) allow tests to be skipped", [human])
    sp.add_argument("tests", nargs="*", metavar="test-id", help="test ids, or /regex/")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--all-new", action="store_true", help="every new skip in the latest gate run")

    sp = cmd("history", _lazy(c, "cmd_history"), "recent gate runs")
    sp.add_argument("--limit", type=int, default=20)

    cmd("doctor", _lazy(c, "cmd_doctor"), "validate config, sprint files, globs, hooks and the registry")

    sp = cmd("register", _lazy(c, "cmd_register"), "add a project to the dashboard registry")
    sp.add_argument("path", nargs="?")
    sp = cmd("unregister", _lazy(c, "cmd_unregister"), "remove a project from the dashboard registry")
    sp.add_argument("path", nargs="?")

    sp = cmd("ui", _lazy("sprintwarden.ui.server", "cmd_ui"), "local dashboard for all registered projects")
    sp.add_argument("--port", type=int, default=7777)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--open", action="store_true", help="open a browser")

    sp = cmd("export", _lazy(c, "cmd_export"), "full status for CI or other tools")
    sp.add_argument("--format", choices=["json", "markdown"], default="json")

    sp = cmd("note", _lazy(lc, "cmd_note"), "append a dated decision to the active sprint's notes")
    sp.add_argument("text", nargs="+")

    sp = cmd("hook", _lazy("sprintwarden.hooks", "cmd_hook"), "hook entry points (called by agents and git)")
    sp.add_argument(
        "name",
        choices=[
            "claude-stop", "claude-pretool", "session-start", "pretool", "pre-push",
            "cursor-stop", "codex-stop", "gemini-after-agent", "copilot-agent-stop",
        ],
    )
    sp.add_argument("hook_args", nargs="*")

    sp = cmd("install-hooks", _lazy("sprintwarden.hooks.install", "cmd_install_hooks"), "install agent/git hooks")
    sp.add_argument("--agent", action="append", default=[], help="claude, cursor, codex, gemini, copilot, git")
    sp.add_argument("--with-guard", action="store_true", help="Claude Code: add the PreToolUse guard")

    cmd("mcp", _lazy("sprintwarden.mcp", "cmd_mcp"), "serve sprintwarden tools over MCP (stdio)")
    return p


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower()
        if enc and enc.replace("-", "") not in ("utf8",) and not stream.isatty():
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            except (AttributeError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    as_json = bool(getattr(args, "json", False))
    cwd = Path(getattr(args, "directory", None) or os.getcwd())
    style = Style.for_stream(sys.stdout, no_color=bool(getattr(args, "no_color", False)))
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not as_json
    env = Env(cwd=cwd, json=as_json, style=style, interactive=interactive)
    try:
        outcome = args.handler(env, args)
    except HumanOnlyError as exc:
        return _error(env, exc, kind="human-only")
    except SprintError as exc:
        return _error(env, exc)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    if as_json:
        if outcome.data or outcome.text == "":
            sys.stdout.write(dumps_json(outcome.data))
    elif outcome.text:
        print(outcome.text)
    return outcome.code


def _error(env: Env, exc: SprintError, kind: str = "error") -> int:
    if env.json:
        sys.stdout.write(dumps_json({"ok": False, "error": str(exc), "hint": exc.hint, "kind": kind}))
    else:
        print(f"sprint: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"  {exc.hint}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
