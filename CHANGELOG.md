# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Sprint S03: Enforcement + packaging (v0.1) (2026-10-12)

Goal: Agents can't finish, push or merge with a broken ratchet; v0.1 is installable via pipx, the Claude Code plugin and the GitHub Action

- AC1: Claude Code Stop hook blocks on a failing gate, allows on pass and never loops forever
- AC2: Agent detection and the human-only guard
- AC3: pre-push hook blocks on failure, chains to existing hooks, SPRINT_SKIP=1 is recorded
- AC4: PreToolUse guard warns about deleted or skipped tests and edits to .sprint state
- AC5: SessionStart briefing, MCP server and other agents' stop hooks

Tests: 278 (+79 since the previous baseline) · tag `sprint-S03`

## [0.1.0] - 2026-10-12

First release: the **test ratchet**, usable on its own (`sprint init --ratchet-only`).

### Added

- `sprint init --ratchet-only`: detects the stack (Gradle, Maven, pytest, Vitest,
  Jest, Go, Swift, cargo-nextest, .NET, or a custom command), runs the suite,
  writes the baseline, `AGENTS.md`, the `CLAUDE.md` import, Claude Code hooks, a
  git pre-push hook and `.gitignore` entries. Idempotent; never overwrites.
- `sprint gate`: runs the full suite, parses JUnit XML and checks for failures,
  tests missing vs the baseline, new skips and a shrinking suite. Failures are
  attributed to the sprint that introduced the test ("REGRESSION from sprint S01").
- Human-only `sprint baseline`, `accept-removal` and `allow-skip`, with reasons
  recorded in `.sprint/`.
- `sprint history`, `status`, `doctor`, `export`, `register`/`unregister`.
- Claude Code: Stop hook with change detection, failure replay and a loop guard;
  SessionStart briefing; optional PreToolUse guard; a plugin with
  `/sprintwarden:sprint-status`.
- Experimental stop hooks for Cursor, Codex, Gemini CLI and Copilot
  (`sprint install-hooks --agent ...`), and an MCP server (`sprint mcp`).
- Reusable GitHub Action (`uses: sprintwarden/sprintwarden@v1`) with a job
  summary, annotations and `--baseline-ref` against the PR's base branch; shell,
  GitLab and Jenkins snippets.
