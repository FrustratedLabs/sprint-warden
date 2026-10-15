# Sprint lifecycle

Sprints are an optional layer on top of the ratchet: `sprint init` (without
`--ratchet-only`), or set `project.mode = "sprints"` later.

```
sprint new "Reports"      →  .sprint/sprints/S03-reports.md   (planned)
  edit goal + acceptance criteria
sprint start S03          →  status active, config sprint.current = S03
  agents implement; tests named S03_…; `sprint note "…"` for decisions
sprint gate               →  checks + AC state, any time
sprint close S03          →  (human) gate passes on a clean HEAD + all ACs satisfied
                              → baseline, status closed, CHANGELOG entry,
                                commit + tag sprint-S03

sprint park S05 --reason "not this quarter"   →  status parked (from planned or active)
sprint unpark S05                             →  back to planned
sprint start S05                              →  or straight back to active
```

On the dashboard's board these are the four columns: **Planned**, **In progress**
(active), **Done** (closed) and **Parked**.

## Sprint file

```markdown
+++
id      = "S03"
title   = "Reports"
status  = "active"          # planned | active | closed | parked
goal    = "User can export the monthly report as PDF"
started = 2026-10-06
closed  = ""
out_of_scope = ["scheduling", "email delivery"]

[[ac]]
id    = "AC1"
desc  = "Export button on dashboard produces a PDF"
tests = ["S03_exportsPdf"]                 # substring or /regex/ on the full test name

[[ac]]
id    = "AC2"
desc  = "Empty month shows a placeholder page"
tests = ["/S03_.*Placeholder.*/"]
+++

## Notes / decisions
- 2026-10-07: chose server-side PDF rendering (agent: claude-code)
```

Rules:

- Exactly one sprint may be `active`, and it must equal `config.sprint.current`
  (`sprint doctor` checks this).
- AC `tests` entries match `"<classname>.<name>"`: a plain string is a substring;
  `/.../` is a regex (`/.../i` for case-insensitive).
- An AC is **satisfied** when ≥1 test matches and all matching tests passed in the
  latest gate run. Skipped doesn't count as passed.
- Put `out_of_scope` **before** the `[[ac]]` tables. (In TOML, a key after a table
  belongs to that table; sprintwarden tolerates it anyway.)

## What blocks what

| | gate | close |
|---|---|---|
| failing tests (any sprint) | ✗ | ✗ |
| missing tests / new skips / ratchet | ✗ | ✗ |
| active sprint has no tests (`require_current_sprint_tests`) | ✗ | ✗ |
| an AC not satisfied | reported | ✗ |
| dirty working tree | — | ✗ |

## Closing

`sprint close S03` is human-only. It runs the gate (or `--no-run` reuses the latest
run if it matches the current tree), then:

1. writes `.sprint/baseline.json` (reason `close S03`) and marks the run as a milestone;
2. sets `status = "closed"`, `closed = <today>` and clears `sprint.current`;
3. adds an entry to `CHANGELOG.md`: under `## [Unreleased]` if there is one,
   otherwise newest first;
4. commits `.sprint/` and `CHANGELOG.md` (`--no-commit` to skip) and creates the
   annotated tag `sprint-S03` (`--no-tag` to skip).

## Parking

Plans change. `sprint park <id> --reason "…"` moves a planned or active sprint to
`status = "parked"` and records `parked = <today>` and `parked_reason` in its
front matter, plus a dated line in its notes. Parking the active sprint also
clears `sprint.current`, so no sprint is active until you `sprint start` one.
`sprint unpark <id>` returns it to `planned`, and `sprint start <id>` works
straight from parked. Closed sprints can't be parked: they're done.

Parking changes nothing in the ratchet. Tests a parked sprint already has stay in
the baseline, so deleting or skipping them still fails the gate. Like planned
sprints, parked ones may list ACs that have no tests yet.

## Long-running projects

- Sprint ids are numbers: S01 … S99, S100 … (`S3` and `S003` both mean `S03`).
- Old closed sprints stay in `.sprint/sprints/` and stay protected by the ratchet
  forever; their failing tests are labelled "REGRESSION from sprint S01".
- Tests from before sprintwarden are the `legacy` bucket.
- Changing the naming scheme? Set `[sprint] id_pattern` (one capture group = the
  sprint number).
