# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Sprint S05: Dashboard (2026-10-12)

Goal: One local, read-only portfolio dashboard across every registered project

- AC1: Registry-backed read-only JSON API: /api/projects, /api/projects/<key>, /api/projects/<key>/runs
- AC2: Portfolio status is correct: pass, fail, stale (run older than HEAD), none, error; failing first
- AC3: Localhost-only and read-only: Host check, no writes, no path traversal
- AC4: The five views render in a real browser (portfolio, timeline, matrix, trends, run detail)

Tests: 315 (+15 since the previous baseline) · tag `sprint-S05`

### Sprint S04: Sprints layer (2026-10-12)

Goal: Sprints, acceptance criteria and computed 'done' on top of the ratchet

- AC1: `sprint new` creates the next numbered sprint; `sprint start` activates exactly one sprint
- AC2: The gate computes AC state from passing tests and labels regressions from closed sprints
- AC3: `sprint close` (human) requires a passing gate on a clean HEAD and every AC satisfied, then baselines, tags and updates CHANGELOG
- AC4: `sprint status` shows the sprint, AC states and regressions per sprint; `sprint note` records decisions
- AC5: A multi-sprint lifecycle works end to end

Tests: 300 (+22 since the previous baseline) · tag `sprint-S04`

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

### Sprints

Built and tracked with sprintwarden itself: S01 parsing core (`sprint-S01`),
S02 ratchet MVP (`sprint-S02`), S03 enforcement + packaging (`sprint-S03`,
5/5 ACs satisfied by passing tests, baseline 278 tests).
