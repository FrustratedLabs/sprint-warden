# Adding a stack

sprintwarden never talks to a test framework. A "stack" is just a template that
`sprint init` copies into `.sprint/config.toml`: a command that writes JUnit XML,
where the XML lands, and how to detect the stack. Adding one needs **one TOML
file**, and no code.

## 1. Write the template

Create `sprintwarden/templates/stacks/<name>.toml` (to contribute it), or
`~/.sprintwarden/stacks/<name>.toml` (just for you; it overrides built-ins):

```toml
# Bazel. Name tests S01_doesThing.
name = "bazel"
label = "Bazel"
priority = 70                 # higher wins when several stacks are detected
example_test = "S01_doesThing" # shown in AGENTS.md and the SessionStart briefing

[[detect]]                    # any rule matching a file at the repo root selects the stack
file = "MODULE.bazel"
[[detect]]
file = "WORKSPACE*"
[[detect]]
file = "BUILD"
contains = "java_test"        # optional: the file must contain this text

[test]
command = "bazel test //... --test_output=errors"
command_windows = ""          # optional Windows variant
reports = ["bazel-testlogs/**/test.xml"]   # globs relative to the repo root; ** = any depth
sources = ["**/*Test.java"]   # test files, for the optional PreToolUse guard

[test.env]                    # optional environment variables for the command
# SOME_VAR = "value"
```

Guidelines:

- Prefer writing XML under `.sprint/out/` when the runner lets you choose; it's
  gitignored, and `clean_reports_before_run` deletes stale files there.
- The command should run **the whole suite**. The gate always does; per-test
  filtering is a non-goal.
- Test identity is `classname + "." + name`. Make sure your runner's names are
  stable between runs (no timestamps or random IDs in names).
- Note how to name tests so the default `id_pattern` attributes them: the sprint id
  must not be glued to a preceding letter or digit (`test_S01_x` and `S01_x` work,
  `TestS01X` doesn't).

## 2. Add a real fixture

Run the stack on a tiny project with this scenario and save the XML as
`tests/fixtures/junit/<name>.xml` (scrub hostnames, usernames and absolute
paths):

1. `S01_login_succeeds`: passes
2. `S01_logout_clears_session`: passes
3. `S02_invoice_rounds`: fails with `expected 10 but was 11`
4. `S02_invoice_pdf`: skipped (`not ready`)
5. `health_check` (no sprint id): passes
6. `S02_crashes`: throws `boom`
7. `[S03] export produces pdf` (or `S03_export_produces_pdf`): passes

Add the expected `(id, outcome, sprint)` rows to `tests/test_s01_junit_fixtures.py`
and a line to `tests/fixtures/junit/README.md` (tool, version, command).

## 3. Check

```sh
python -m pytest -q tests/test_s01_junit_fixtures.py tests/test_s01_config.py
```

Then try it for real: `sprint init --ratchet-only --stack <name>` in a sample
project, delete a test, and check that `sprint gate` reports it as missing.

## Known stack quirks

- **Swift (SwiftPM xunit)** has no skipped element; `XCTSkip` tests show as passed,
  so new skips can't be detected. Missing tests still are.
- **cargo-nextest** omits `#[ignore]` tests from JUnit, so an ignored test shows up
  as *missing*. It is still blocked, with a different label.
- **go-junit-report** reports the parent of subtests as its own test.
- **jest-junit** uses the test title as both classname and name by default
  (`S01_x.S01_x`). That's stable, which is what matters.
- **Gradle** test-retry plugin reports a retried test twice; a duplicate counts as
  failed if any attempt failed.
