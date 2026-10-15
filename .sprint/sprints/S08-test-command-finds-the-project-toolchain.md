+++
id      = "S08"
title   = "Test command finds the project toolchain"
status  = "active"          # planned | active | closed | parked
goal    = "The gate runs a project's tests with the project's own environment (its .venv), says clearly when the interpreter is wrong, and the Stop hook stops nagging about a problem the agent can't fix"
started = 2026-10-15
closed  = ""
out_of_scope = ["managing or creating virtualenvs (sprintwarden only finds them)", "Node/JVM version managers (nvm, sdkman)", "Phase 7 integrations"]

# Acceptance criteria. An AC is satisfied when at least one test matches and
# every matching test passed in the latest `sprint gate` run.
[[ac]]
id    = "AC1"
desc  = "The test command runs with the project's virtualenv first on PATH (.venv/, venv/, or $VIRTUAL_ENV), as if it were activated, with no config change"
tests = ["/test_S08_venv_/"]

[[ac]]
id    = "AC2"
desc  = "[test] path names other folders to put first on PATH, and [test] use_venv = false turns the lookup off"
tests = ["/test_S08_test_path_/"]

[[ac]]
id    = "AC3"
desc  = "When `python` is missing or is Python 2, the gate says so in plain words and how to fix it, instead of \"no JUnit XML found\""
tests = ["/test_S08_interpreter_/"]

[[ac]]
id    = "AC4"
desc  = "`sprint doctor` shows which interpreter and PATH folders the gate will use, and warns about the problems in AC3"
tests = ["/test_S08_doctor_/"]

[[ac]]
id    = "AC5"
desc  = "A test command that can't start (environment problem) is reported to the agent once; on an unchanged tree the Stop hook then lets the session end and tells the human, while build and test failures still block"
tests = ["/test_S08_hook_/"]

+++

## Notes / decisions
- 2026-10-15: Gate puts the project venv (.venv, venv, $VIRTUAL_ENV) first on PATH, checks a leading python before running, marks environment failures; Stop hook reports those once per gate run (D-032). Planned ACs written into the S08 file before sprint start. (agent: claude-code)
