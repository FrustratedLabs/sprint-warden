# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
