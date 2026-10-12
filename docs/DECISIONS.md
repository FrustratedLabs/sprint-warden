# Decisions

Where the build spec left something open, or where following it literally would
have caused a bug, the choice is recorded here. Newest last. "Spec" means
`sprintkit-build-spec.md`, the document this project was built from.

## D-001 · Name: sprintwarden (spec §3)

`sprintkit` is taken on PyPI (an unrelated 2013 package). The project ships as
**sprintwarden** (free on PyPI, npm and GitHub at the time of writing). The CLI is
still `sprint` (plus a `sprintwarden` alias in case `sprint` collides with another
tool), the per-project folder is `.sprint/` and the global folder is
`~/.sprintwarden/` (override with `SPRINT_HOME`). URLs use the placeholder
`github.com/sprintwarden/sprintwarden`; replace the owner when publishing.

Runtime stays standard-library only (spec §2.8). Dev tools (pytest, ruff) are a
dependency group.

## D-002 · Default `id_pattern` allows an underscore before the sprint ID

The spec's pattern `(?i)\bS(\d{2,})(?:[_\]\s:-]|$)` never matches pytest, XCTest or
Go test names: `test_S03_x` has no word boundary between `_` and `S`. The default
is now

    (?i)(?<![A-Za-z0-9])S(\d{2,})(?=[_\]\s:.()\[/-]|$)

The ID must not be glued to a preceding letter or digit (`BS03` and `class1S03`
don't match), must end at a separator (`S03exports` doesn't match), and can be
followed by `.`, `(`, `[`, `/` too (JUnit 5 `()`, parametrized `[...]`, Go
subtests). The spec's pattern still works if set explicitly.

Attribution searches the test **name** first and falls back to the **classname**,
so a class `S04_BillingTest` attributes all its methods to S04 while a method
`S05_x` inside it still wins. Sprint IDs are normalized to two or more digits
(`S3` and `S003` → `S03`, `S100` stays) and sorted numerically, for projects that
run past S99.

## D-003 · `out_of_scope` after `[[ac]]` tables

In TOML, a key written after `[[ac]]` belongs to the last AC table, so the
spec's own example puts `out_of_scope` inside AC2. The parser hoists it back to
the sprint, and the generated template puts it before the AC tables.

## D-004 · Stop-hook "nothing changed" uses a content fingerprint, and replays failures

The spec says to skip the gate when HEAD and the `git status --porcelain` hash are
unchanged. Porcelain alone misses a second edit to an already-modified file (its
status line is still ` M file`), which would let an agent stop with a broken
build. The fingerprint is HEAD + porcelain + size/mtime of every changed or
untracked path, excluding files the gate itself writes (`.sprint/runs`,
`.sprint/latest.json`, `.sprint/out`).

If nothing changed and the last result was a **failure**, the hook replays that
failure (exit 2) instead of exiting 0, and it counts toward the loop guard.
Otherwise an agent could stop by trying twice without fixing anything.

## D-005 · Acceptances are time-scoped to the baseline

`removals.json` and `skips.json` entries record when they were accepted. An entry
only applies to baselines taken **before** it. As a result:

- a removal accepted long ago can't exempt a test that was later re-added and
  re-baselined;
- `sprint baseline` doesn't need to prune entries, so `removals.json` is a
  permanent, reviewable log;
- CI can compare a branch against the main branch's baseline
  (`--baseline-ref origin/main`) while honouring removals a human accepted on
  the branch. Those are listed in the job summary for reviewers.

Timestamps use millisecond precision because accept → baseline can happen
within one second.

## D-006 · `init` writes a baseline in both modes; failing tests block it

The spec runs the first gate and writes the baseline in ratchet-only mode. Sprints
mode does the same (skip with `--no-gate`); otherwise legacy tests would be
unprotected until the first `sprint close`. If tests fail today, no baseline is
written and `init` exits 1 with instructions: fix them, or skip them in code (the
skip is recorded in the baseline), then run `sprint baseline`. There is no
separate "known failures" concept.

## D-007 · What "passing gate" means for `baseline`

`sprint baseline` requires the **ratchet checks** (runner, failures, missing,
skips, ratchet) to pass on a clean HEAD. The sprint checks (`sprint_tests`, ACs)
don't block it, so you can re-baseline mid-sprint, e.g. after accepting removals.
`sprint close` requires everything.

## D-008 · `require_current_sprint_tests` blocks the gate when the active sprint has no tests

ACs only block `close` (spec §9.3). The config flag
`require_current_sprint_tests` (spec §5, otherwise unspecified) makes the gate fail
while the active sprint has **zero** attributed tests: "cover it with tests" is
enforced from the first agent stop.

## D-009 · A runner that exits non-zero without failing tests fails the gate

A non-zero exit with failing tests is expected. A non-zero exit with **no** failing
tests usually means a build error, so some module's tests silently didn't run.
`[gate] fail_on_runner_error = true` (default) fails the `runner` check in that
case. Set it to false for commands that also run linters, etc.

## D-010 · Report cleaning is defensive

`clean_reports_before_run` only deletes files that match the report globs, **look
like JUnit XML** (`<testsuite` in the first 4 KB) and are **not tracked by git**. A
careless glob like `**/*.xml` can never delete `pom.xml`. While expanding `**`,
directories such as `node_modules`, `.git` and virtualenvs are skipped for speed;
spelling them out explicitly still works.

## D-011 · Multiple test suites (monorepos)

Besides `[test] command/reports`, `[[test.suites]]` entries (name, command, reports,
cwd, timeout_minutes, env) run in order and their results are merged. Test
identity is unchanged (no suite prefix), so adding a second suite never renames
existing baseline entries.

## D-012 · Long-lived projects: sharded, capped history

Run records go to `runs/YYYY-MM/<id>.json`. Lists in committed run files are
capped at 200 entries (counts are exact). `[history] keep = N` prunes the oldest
runs but never milestones (`init`, `baseline`, sprint closes). The uncapped
results of the latest run live in `.sprint/out/latest-full.json` (gitignored),
used by `accept-removal --all-missing` and `allow-skip --all-new`.
`latest.json` = the latest run record plus `acs_all` (every sprint's ACs), for
the dashboard. The spec's `history_in_git` setting is `[history] in_git`.

## D-013 · One gate per working tree at a time

Parallel agents in the same checkout share report files, so the gate takes
`.sprint/out/gate.lock` (stale locks from dead processes are ignored). Separate
git worktrees don't share a lock and don't need to.

## D-014 · The pre-push hook is a tiny `sh` shim

Git for Windows runs hooks through its bundled `sh`, so a POSIX shim that calls
`sprint hook pre-push` (falling back to the interpreter sprintwarden was installed
with) works on all three OSes. All logic is Python. An existing hook is moved to
`pre-push.local` and still runs first. With husky (`core.hooksPath` under
`.husky`), a line is appended to `.husky/pre-push` instead.

## D-015 · Bypass records don't overwrite latest.json

`SPRINT_SKIP=1 git push` writes a run record with `"bypassed": true` and
`"result": "bypassed"`, but leaves `latest.json` alone because no gate ran.

## D-016 · Known stack quirks (from the real fixtures)

- SwiftPM's xunit output has no skipped element: XCTSkip tests show as passed,
  so new skips can't be detected on Swift. Missing tests still are.
- cargo-nextest omits `#[ignore]` tests from JUnit entirely, so an ignored Rust
  test shows up as **missing** (still blocked, with a different label).
- go-junit-report emits the parent of subtests as its own test case.
- jest-junit uses the title as both classname and name; IDs look like
  `S01_x.S01_x`. They are stable, which is what matters.

## D-017 · Stop hook verified live against Claude Code

The Stop hook contract was checked against the current docs and then end to end
with Claude Code in a throwaway repo: the agent answered without tools, the hook
blocked with exit 2 ("REGRESSIONS … [S01] …"), Claude fixed the code and ran the
gate, and the next stop was allowed from the cached pass. Claude Code labels
**any** Stop-hook block "Stop hook error occurred" in its notification, whether
it's exit 2 or JSON `decision: block`, so we keep exit 2 + stderr as the spec says.
When the loop guard lets the agent go, a JSON `systemMessage` on exit 0 tells the
human.

A second copy of the hook (project settings + plugin) fires for the same stop with
an identical payload. Identical payloads within 2 s count once toward the loop
guard. A genuine retry needs a model turn, so it is always counted.

## D-018 · Agent-run closes in this repository are labelled

While building sprintwarden, Claude Code built the phases and closed the dogfood
sprints with `sprint close --i-am-human`, at the maintainer's request (spec §13:
"each phase is a sprint"). sprintwarden records that override in the close
commit ("Closed by: … (--i-am-human, in claude-code)"), so it shows in history.
That's the intended behaviour: the guard is a speed bump, and an override leaves a trace.

## D-019 · README demo is an animated SVG generated from the real demo

`docs/demo.sh` runs the real scenario (an agent deletes an old test; plain pytest
goes green; `sprint gate` blocks with "REGRESSION from sprint S01" and "missing vs
baseline"). `docs/make_demo_svg.py` renders its actual output as an animated SVG,
a few KB, crisp, and regenerated in one command. `docs/demo.tape` produces a GIF
with VHS for places that need one.

## D-020 · Init registers the project globally

`sprint init` adds the project to `~/.sprintwarden/registry.toml` (spec §8) so
`sprint ui` finds it. Tests and demos isolate this with `SPRINT_HOME`.

## D-021 · Permanent skip allowances for environment-dependent tests

Found while dogfooding S05: a browser test that runs in CI but is skipped on a
laptop without Playwright's Chromium. With time-scoped allowances (D-005) it
would need re-allowing after every baseline. `sprint allow-skip --permanent`
(human-only, reason required) records `"permanent": true`, and that allowance
applies to every baseline. Use it for OS- or toolchain-specific tests only; an
ordinary allowance still expires at the next baseline, so a skip that was
meant to be temporary can't become permanent by accident.
