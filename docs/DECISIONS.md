# Decisions

Where the build spec left something open, or where following it literally would
have caused a bug, the choice is recorded here. Newest last. "Spec" means
`sprintkit-build-spec.md`, the document this project was built from.

## D-001 · Name: sprintwarden (spec §3)

`sprintkit` is taken on PyPI (an unrelated 2013 package). The project ships as
**sprintwarden** (free on PyPI, npm and GitHub at the time of writing). The CLI is
still `sprint` (plus a `sprintwarden` alias in case `sprint` collides with another
tool), the per-project folder is `.sprint/` and the global folder is
`~/.sprintwarden/` (override with `SPRINT_HOME`). The repository is
`github.com/FrustratedLabs/sprint-warden`.

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

## D-022 · latest.json is a local cache, not committed by default

The spec commits `latest.json`. Running the example scenarios showed the cost:
every gate run rewrites that tracked file, so `git checkout other-branch` fails
with "local changes would be overwritten", and parallel branches and agents get
merge conflicts on it all the time. The durable history lives in `runs/`, which
is committed: one uniquely named file per run, so it never conflicts.
`latest.json` is now gitignored by default. Readers (status, hooks, the
dashboard) fall back to the newest committed run when it's absent, e.g. in a
fresh clone. `[history] latest_in_git = true` restores the spec's behaviour.

## D-023 · A fourth sprint status: parked

Requested for long-running products: besides planned, in progress and done, a
board needs a place for work that was set aside. The spec's statuses are
`planned | active | closed`; `parked` is added, not substituted, so existing
sprint files keep their meaning. `sprint park <id> [--reason]` and
`sprint unpark <id>` are ordinary commands, not human-only: parking can't make
a failing gate pass, because the parked sprint's tests stay in the ratchet
(D-005's baseline rules apply unchanged). Parking the active sprint clears
`sprint.current`. The date and reason live in front matter (`parked`,
`parked_reason`) so the board can show them, and a dated line goes to the notes.

## D-024 · The board is read-only, and moves happen in the CLI

The spec lists "editing sprint files from the UI" as a non-goal, and the
dashboard is read-only (it rejects every non-GET). So the board has no drag and
drop: each card's detail panel shows the command that moves it
(`sprint start`, `close`, `park`, `unpark`). Columns map one-to-one to statuses.
Planned is ordered by sprint number, and the lowest planned sprint is "Up next".
Done is newest first. A done sprint is flagged "regressed" when any of its
tests fail or are missing in the latest run. `GET /api/board` returns every
sprints-mode project's sprints in one request for the all-projects board.

## D-025 · Lucide icons vendored as data

The UI must have no CDN and no build step (spec §2.8, fixed). The 50 Lucide icons
it uses are vendored into `ui/static/icons.js` as element/attribute arrays, and
app.js builds them with `createElementNS`. So there's no `innerHTML`, no SVG
sprite request, and nothing the CSP has to allow. `docs/vendor_lucide.py`
regenerates the file from a pinned `lucide-static` release (1.48.0). Lucide is
ISC-licensed, with some icons from Feather (MIT); the full text ships as
`sprintwarden/ui/LICENSE-lucide.txt`, and the footer credits it. Status marks are
Lucide icons as well (D-028). The header mark and favicon are not Lucide: they are
the five-bar gate from `brand/` (D-031).

## D-026 · Sprints stays the default project tab

The project page gains a Board tab, but the Sprints timeline stays the default
because the S05 browser test opens a project and expects the timeline. The
top-level Board view (all projects) is one click from anywhere. Making Board the
default is a one-line change plus an update to that S05 test, which AGENTS.md
says a human has to approve.

## D-027 · A theme button on top of prefers-color-scheme

The spec asks for light/dark via `prefers-color-scheme`, and that stays the
default. A top-bar button cycles match system → light → dark and saves the choice
in the browser's localStorage (`sprintwarden.theme`). It sets `data-theme` on
`<html>`: the system dark palette applies only to `:root:not([data-theme="light"])`,
and `:root[data-theme="dark"]` forces it. Both blocks carry the same tokens, and
a test keeps them identical. A small `theme.js` in `<head>` applies the saved
choice before first paint, because the CSP forbids inline scripts and a script at
the end of `<body>` would flash the wrong theme.

## D-028 · Status marks are Lucide icons, not text glyphs

Spec §11 says to pair colour with "✓/✗ text". The redesign drew status that way
(plus ⏱ ○ ● ‖ ∅ ⊘ ◆ ⚠ for the other states), and in the UI font those characters
came out at odd sizes and weights next to the Lucide icons. The human chose
"Lucide everywhere" (2026-10-14): every mark is now a Lucide icon (check, x, clock,
skip-forward, circle-dashed, diamond, …) from one `MARK` table in app.js. The rule
behind §11 still holds, because the icon is never the only cue: pills and chips
keep their word ("FAIL", "done", "skipped"), and a mark without a word next to it
carries an `aria-label` and a `<title>`. The S05 browser test pinned the literal
"⏱ STALE", "✓ PASS" and "✗ FAIL" text; with the human's OK it now checks for the
same pill with its Lucide icon followed by the word. The CLI output keeps ✓/✗,
because terminals have no icons.

## D-029 · Full or compact board cards

The board has a Full / Compact switch. A compact card shows only the sprint ID,
the project key on the all-projects board, the title and the AC bar, so a long
roadmap fits on one screen; the panel still has everything else. The choice is
kept in the browser (`sprintwarden.board.cards` in localStorage) and applies to
both boards. `?cards=compact` (or `full`) in the URL picks one too, which makes a
compact view linkable and testable without browser storage.

## D-030 · Trends: one measure per chart, explained in plain words

The old Trends chart drew total tests and pass rate on two y-axes, which invents
a correlation between unrelated scales and meant little to someone who doesn't
know the ratchet. It is now two charts that share the run axis (tests in each
run; pass rate in each run), with failed runs marked by an × as well as colour,
labelled milestones, and an end label for the latest value. Above them: four
headline numbers and "What this tells you", sentences computed in the browser
from the same runs (latest result and streak, regressions, growth and drops,
share of failed runs, change since the last milestone, which sprints' tests
fail). Below: "Why it matters". A crosshair readout follows the pointer across
both charts; the arrow keys, Home and End step through runs, and Enter or a click
opens one. The Runs tab is the table view of the same data. No server change:
everything comes from `/api/projects/<key>/runs`.

## D-031 · The five-bar gate is the dashboard's mark and favicon

The brand kit in `brand/` defines the mark: four tally bars with one red bar
across them (a "five-bar gate", like `sprint gate`). The dashboard header draws
it inline, with the bars in `currentColor` so they follow the theme, and the
favicon is the kit's 16 px pixel-grid version. Both are written without the
C2PA metadata block the exported files carry, because the static files must
contain no `http://` URLs other than the SVG namespace (S05). With the human's
OK, the S07 icon test now checks for the five-bar gate in both places instead
of Lucide's shield-check.
