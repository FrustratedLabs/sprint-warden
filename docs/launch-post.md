# Your coding agent deleted a test to make the build green. Here's a ratchet for that.

*Draft for Hacker News / r/ClaudeAI / dev.to. Edit freely.*

If you've used coding agents on a real codebase for more than a few weeks, you've
probably seen this. You ask for a feature. The agent implements it, runs the
tests, and one of them, written three sprints ago for something unrelated, goes
red. The agent tries a couple of fixes. Then the report says:

> All tests pass. ✅

And they do. There are just fewer of them. Somewhere in the diff, among 400
changed lines, a test function is gone, or wrapped in `@Disabled`, or its
assertion has quietly become `assertTrue(true)`.

This isn't malice. The agent is optimising for the signal you gave it, "make the
tests pass", and deleting the failing test is the shortest path there. Humans
do it too under deadline pressure; agents just do it faster, more often, and
in diffs too big to review line by line. The longer the project runs, the
worse it gets: agents don't remember that `test_lockout_after_5_attempts`
exists because of a security incident in March.

## Before

Here is the failure in miniature. A small invoicing module has a sprint-1 test
for half-up rounding:

```python
def test_S01_rounds_half_up():
    assert to_cents("1.005") == 101
```

In sprint 2 an agent "simplifies" `to_cents` with float maths, and that test
fails (`100 != 101`). Two turns later the test is gone, `pytest` is green, and
the agent reports success. Nothing in your toolchain objects, because from
pytest's point of view the suite simply got smaller.

## After

[sprintwarden](https://github.com/FrustratedLabs/sprint-warden) is a **test ratchet**.
`sprint init --ratchet-only` runs your suite once and records every test that
exists today in `.sprint/baseline.json`. From then on `sprint gate` checks four
things on every run:

- **no failing tests**, in any sprint, and failures are labelled with the sprint
  that introduced the test;
- **no missing tests**: every baseline test still exists;
- **no new skips**;
- **the ratchet**: the test count never goes down.

The same scenario, with sprintwarden:

```
$ pytest -q
3 passed in 0.01s
$ sprint gate
✓ runner     3 tests parsed from 1 file (0.1s)
✓ failures   no failing tests
✗ missing    1 test missing vs baseline
     S01    tests.test_invoice.test_S01_rounds_half_up  ← deleted or renamed? use `sprint accept-removal` (human only)
✗ ratchet    3 < 4: the suite shrank
GATE: FAIL
```

A test can still be removed on purpose. A **human** runs
`sprint accept-removal <test> --reason "merged into test_rounding_table"`, and
the reason is committed next to it, where code review will see it.

## Enforcement that agents actually hit

A check the agent can skip is a suggestion, so the gate is wired into the
places where "done" happens:

- **Claude Code**: a Stop hook. The agent can't end its turn while the gate fails;
  it gets a compact report ("REGRESSIONS: [S01] AuthTest.lockout… Fix these; do
  not delete or skip tests") and keeps working. Change detection keeps the hook
  free when nothing changed, and a loop guard lets go after three attempts and
  tells you.
- **Cursor, Codex, Gemini CLI, Copilot**: generated `AGENTS.md` rules, plus
  experimental stop hooks for each.
- **git push**: a pre-push hook (bypassable with `SPRINT_SKIP=1`, and the bypass is
  recorded).
- **CI**: a GitHub Action that compares the branch against the **main branch's**
  baseline. So "delete the test *and* edit the baseline in the same commit"
  doesn't work either.

## Sprints, optionally

Long agent-driven projects tend to run in sprints anyway. If you name tests with
the sprint id (`S03_exportsPdf`, `test_S03_…`, `describe("[S03] …")`), sprintwarden
attributes every result to a sprint. A failure then reads "REGRESSION from
sprint S01", not just "test failed". Sprint files hold acceptance criteria as
test patterns, and **"done" is computed**: an AC is satisfied only when its tests
exist and pass. `sprint close S03` refuses until they do, then snapshots the new
baseline, tags the commit and writes the changelog entry.

There's a local, read-only dashboard (`sprint ui`) with a regression matrix
(sprints × runs) across all your projects.

## Design choices

- **Any stack.** sprintwarden never talks to a test framework. It runs your
  command and reads JUnit XML: Gradle, Maven, pytest, Vitest, Jest, Go, Swift,
  Rust, .NET, or anything else that writes it.
- **Plain files in git.** No server, no database, no telemetry. The baseline is a
  sorted JSON file, one test per line, so a shrinking baseline is obvious in a diff.
- **Zero dependencies.** Python standard library only, so `pipx install sprintwarden`
  is instant.
- **Honest about its limits.** "Human-only" commands detect agent environments and
  refuse, but that's a speed bump, not security, and the docs say so. CI plus
  review of `.sprint/` changes is the real authority.

It complements the tools you already have. Spec Kit, Kiro and friends plan the
work; "don't stop until tests pass" hooks catch red builds; sprintwarden catches
the green builds that got green by losing tests.

## Try it

```sh
pipx install sprintwarden
cd your-repo && sprint init --ratchet-only
```

Two minutes on any stack. Feedback and new stack templates are very welcome.
