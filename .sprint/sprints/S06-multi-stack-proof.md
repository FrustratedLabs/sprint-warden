+++
id      = "S06"
title   = "Multi-stack proof (v0.2)"
status  = "planned"          # planned | active | closed
goal    = "Real example projects on several stacks prove the S01-regression story end to end"
started = ""
closed  = ""
out_of_scope = ["Phase 7 integrations (importers, sync providers)"]

[[ac]]
id    = "AC1"
desc  = "pytest example: 2 sprints; an S01 regression branch is labelled 'REGRESSION from sprint S01'; deleting the S01 test is caught"
tests = ["/test_S06_example_pytest_/"]

[[ac]]
id    = "AC2"
desc  = "Vitest, Go and Gradle examples pass the same scenario (where the toolchain is installed)"
tests = ["/test_S06_example_(vitest|go|gradle)_/"]

[[ac]]
id    = "AC3"
desc  = "The dashboard shows every example with the right status, matrix and trends"
tests = ["/test_S06_examples_dashboard_/"]
+++

## Notes / decisions
