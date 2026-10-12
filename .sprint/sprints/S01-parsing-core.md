+++
id      = "S01"
title   = "Parsing core"
status  = "closed"          # planned | active | closed
goal    = "Any stack's JUnit XML parses into attributed test results; sprint files and config load with clear errors"
started = 2026-10-12
closed  = 2026-10-12
out_of_scope = ["running tests", "CLI"]

[[ac]]
id    = "AC1"
desc  = "JUnit XML from Gradle, Maven, pytest, vitest, jest, Go, Swift, nextest and .NET parses to the same scenario"
tests = ["test_S01_fixture_parses_to_the_scenario"]

[[ac]]
id    = "AC2"
desc  = "Tests are attributed to sprints by name on every stack's naming style"
tests = ["test_S01_default_pattern_attributes_every_stack_naming_style"]

[[ac]]
id    = "AC3"
desc  = "AC matching supports substrings and /regex/ on full test ids, at 50k-test scale"
tests = ["/test_S01_(index|ac|matcher)_/"]

[[ac]]
id    = "AC4"
desc  = "Sprint files and config.toml parse, with clear errors for invalid input"
tests = ["/test_S01_(parses_the_spec_example|invalid_sprint_files|loads_the_spec_config|invalid_configs)/"]
+++

## Notes / decisions
- 2026-10-12: default id_pattern allows `_` before the sprint id so pytest/XCTest/Go names attribute (docs/DECISIONS.md D-002) (agent: claude-code)
- 2026-10-12: fixtures generated from the real tools where installed; Swift and .NET reproduced from generator source (agent: claude-code)
