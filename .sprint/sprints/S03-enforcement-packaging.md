+++
id      = "S03"
title   = "Enforcement + packaging (v0.1)"
status  = "active"          # planned | active | closed
goal    = "Agents can't finish, push or merge with a broken ratchet; v0.1 is installable via pipx, the Claude Code plugin and the GitHub Action"
started = 2026-10-12
closed  = ""
out_of_scope = ["sprint lifecycle commands", "dashboard"]

[[ac]]
id    = "AC1"
desc  = "Claude Code Stop hook blocks on a failing gate, allows on pass and never loops forever"
tests = ["/test_S03_stop_hook_/"]

[[ac]]
id    = "AC2"
desc  = "Agent detection and the human-only guard"
tests = ["/test_S03_detect/"]

[[ac]]
id    = "AC3"
desc  = "pre-push hook blocks on failure, chains to existing hooks, SPRINT_SKIP=1 is recorded"
tests = ["/test_S03_pre_push_/"]

[[ac]]
id    = "AC4"
desc  = "PreToolUse guard warns about deleted or skipped tests and edits to .sprint state"
tests = ["/test_S03_pretool_/"]

[[ac]]
id    = "AC5"
desc  = "SessionStart briefing, MCP server and other agents' stop hooks"
tests = ["/test_S03_(session_start|mcp|other_agent)_/"]
+++

## Notes / decisions
