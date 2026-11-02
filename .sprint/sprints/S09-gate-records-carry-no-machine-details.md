+++
id      = "S09"
title   = "Gate records carry no machine details"
status  = "active"          # planned | active | closed | parked
goal    = "What the gate writes to .sprint/ names no folder, login, host or temp path of the machine it ran on, so run records can be committed to a public repo"
started = 2026-11-02
closed  = ""
out_of_scope = ["records already committed (a project can clean those once by hand)", "test IDs that contain a machine path (other runs and the baseline match on them)", "secrets in test output", "the gitignored .sprint/out/ (raw reports and latest-full.json)", "what the gate prints to the terminal, which keeps the full paths"]

# Acceptance criteria. An AC is satisfied when at least one test matches and
# every matching test passed in the latest `sprint gate` run.
# `tests` entries match "<classname>.<name>": a plain string is a substring,
# "/.../" is a regex. Name tests after the sprint, e.g. `test_S01_does_thing`.
[[ac]]
id    = "AC1"
desc  = "A path in the project is written relative to its root, also as a file:// URL or in its ~/ form (`<root>/src/app.py:3` becomes `src/app.py:3`); the root itself is written `.`"
tests = ["/test_S09_project_/"]

[[ac]]
id    = "AC2"
desc  = "Another path in the home folder is written `~/…`, and a path in a temp folder (TMPDIR, /tmp, /var/tmp, and macOS's /private forms) `$TMPDIR/…`"
tests = ["/test_S09_home_temp_/"]

[[ac]]
id    = "AC3"
desc  = "The login and the host name inside a path (`pytest-of-<login>`, `<login>@<host>`) are written `$USER` and `$HOST`, and a folder name a tool made from a path (`-Users-ada-proj`, as Claude Code names its folders) `<project>` when it names the project and `~` when it names another folder in the home folder"
tests = ["/test_S09_login_host_/"]

[[ac]]
id    = "AC4"
desc  = "A path a test framework cut short with `…` or `...`, at either end, is rewritten as far as it goes (`<temp folder, cut>…` becomes `$TMPDIR…`, `...<end of the root>/.venv/bin` becomes `…/.venv/bin`)"
tests = ["/test_S09_cut_/"]

[[ac]]
id    = "AC5"
desc  = "Every string written to runs/ and latest.json is covered: failure and skip messages, file fields, the runner's command, the baseline's source; test and run IDs are kept as they are, and the terminal report still shows the full paths"
tests = ["/test_S09_every_/"]
+++

## Notes / decisions
- 2026-11-02: Built sprintwarden/redact.py (D-033): runs/ records, latest.json and bypass records are rewritten before writing; the terminal report is printed first, so it keeps the full paths. Decisions: test and run IDs are kept (the baseline, close --no-run and the Stop hook match on them); latest-full.json in the gitignored .sprint/out/ is left as is, since close --no-run reads its test IDs; the login and host name are rewritten only inside path-like text, so a login that is also a word (runner on CI) stays a word; host names go before the login, and a host name equal to the login is written $USER; a project root that ends a sentence reads '..' (AC1's '.' plus the full stop). S08 was parked as ready to close so S09 could start. Gate 2026-11-02: PASS, 358 tests, 5 for S09, AC1 to AC5; its own record names nothing of this Mac. (agent: claude-code)
