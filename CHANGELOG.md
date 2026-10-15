# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Sprint board**: a kanban of sprints in four columns (Planned, In progress,
  Done, Parked), per project and across every registered project
  (`GET /api/board`). Done sprints whose tests fail again are flagged
  "regressed", the lowest planned sprint is "Up next", and each card opens a
  panel with its ACs, matched tests, notes and the command that moves it on.
- **Parked sprints**: `sprint park <id> --reason "…"` and `sprint unpark <id>`;
  `sprint start` works straight from parked. A parked sprint's tests stay in the
  ratchet.
- **Compact board cards**: a Full / Compact switch on both boards. Compact cards
  show the sprint ID, title and AC bar only; the choice is remembered, and
  `?cards=compact` links to it.
- **Trends explained**: headline numbers, "What this tells you" (plain sentences
  worked out from the runs), "Why it matters", and a hover / keyboard readout
  for each run.
- `docs/make_screenshots.py` rebuilds the README screenshots from a synthetic
  demo portfolio.

### Changed

- The dashboard is redesigned: neutral paper and ink surfaces, colour only for
  status, serif page titles, Lucide icons (vendored, ISC), a Projects/Board top
  bar, and portfolio cards that show what's up next and a compact sprint
  roadmap. Light and dark follow the system, and a top-bar button forces either
  one (remembered per browser).
- Every status mark in the dashboard is a Lucide icon next to a word, instead of
  ✓ ✗ ⏱ ○ ● ‖ ∅ ⊘ ◆ ⚠ text glyphs; the favicon is Lucide's shield-check.
- Trends shows tests and pass rate as two charts on a shared run axis instead of
  one chart with two y-axes.

## [0.2.0] - 2026-10-12

The full layer cake: sprints and computed "done", the dashboard, and proof on
four stacks.

### Added

- **Sprints layer**: `sprint new`, `start`, `close` (human-only: gate passes on a
  clean HEAD and every acceptance criterion is satisfied by passing tests, then
  baseline + commit + `sprint-<id>` tag + CHANGELOG entry) and `note`. ACs are
  computed in every gate run; failures in closed or earlier sprints are labelled
  "REGRESSION from sprint Sxx"; `status` shows regressions per sprint.
- **Dashboard**: `sprint ui`, a local read-only portfolio over all registered
  projects (pass / fail / stale / none / error, failing first), with a sprint
  timeline, regression matrix, trends chart and run details. Includes an
  "Open in Allure" link and a strict CSP, binds to localhost only, and rejects
  foreign `Host` headers.
- **Examples** for pytest, Vitest, Go and Gradle, each with two sprints and a
  scripted S01-regression branch; `examples/run-all.sh` / `.ps1` asserts the
  outcomes; CI runs them on Linux, macOS and Windows.
- `sprint allow-skip --permanent` for environment-dependent tests (D-021).

### Changed

- `.sprint/latest.json` is a local cache and is gitignored by default; committing
  it blocked branch switches (D-022). Set `[history] latest_in_git = true` for the
  old behaviour. History in `runs/` is still committed.
- Committed run records are compact (per-AC counts, lists capped at 50).

### Sprints

S04 sprints layer (`sprint-S04`), S05 dashboard (`sprint-S05`), S06 multi-stack
proof (`sprint-S06`), all closed with every AC satisfied by passing tests.

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
- Reusable GitHub Action (`uses: FrustratedLabs/sprint-warden@v0`) with a job
  summary, annotations and `--baseline-ref` against the PR's base branch; shell,
  GitLab and Jenkins snippets.

### Sprints

Built and tracked with sprintwarden itself: S01 parsing core (`sprint-S01`),
S02 ratchet MVP (`sprint-S02`), S03 enforcement + packaging (`sprint-S03`,
5/5 ACs satisfied by passing tests, baseline 278 tests).
