---
name: sprint-workflow
description: Use in any repository that has a .sprint/ folder (sprintwarden). Explains how to pick up the active sprint, name tests, run the gate, and what an agent must never do to tests or ratchet state.
---

# Working in a sprintwarden repository

sprintwarden is a test ratchet: every test in `.sprint/baseline.json` must keep
existing, keep running and keep passing. "Done" is computed from passing tests.

## Before you start

1. Run `sprint status`. It shows the active sprint, its goal, each acceptance
   criterion (AC) and whether the last gate passed.
2. Read the active sprint file in `.sprint/sprints/`. Only implement what its
   goal and ACs ask for; anything else, ask the human.

## While you work

- Write the tests for each AC first. Name them with the sprint id after any
  prefix your framework needs: `S03_exportsPdf`, `test_S03_exports_pdf`,
  `Test_S03_ExportsPdf`, `describe("[S03] export")`.
- An AC is satisfied when at least one test matches its `tests` patterns and all
  matching tests pass. Check the patterns in the sprint file.
- Record notable decisions with `sprint note "chose X because Y"`.

## Before you say you're done

Run `sprint gate` and paste its summary. If it fails:

- **failures / REGRESSION**: fix the code. A regression is a test from an earlier
  sprint (or the baseline) that used to pass.
- **missing**: a baseline test no longer exists. Restore it.
- **new skips**: un-skip the test.
- **tests**: the active sprint has no tests named for it yet.

## Never

- Delete, rename, skip, disable or weaken an existing test. If an old test
  conflicts with the new requirement, stop and ask the human.
- Edit files in `.sprint/` (except via `sprint note`).
- Run `sprint close`, `sprint baseline`, `sprint accept-removal` or
  `sprint allow-skip`, or pass `--i-am-human`. These are for humans.
