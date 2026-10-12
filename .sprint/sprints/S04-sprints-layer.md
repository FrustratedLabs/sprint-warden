+++
id      = "S04"
title   = "Sprints layer"
status  = "closed"          # planned | active | closed
goal    = "Sprints, acceptance criteria and computed 'done' on top of the ratchet"
started = 2026-10-12
closed  = 2026-10-12
out_of_scope = ["importing ACs from Spec Kit / OpenSpec (Phase 7)"]

[[ac]]
id    = "AC1"
desc  = "`sprint new` creates the next numbered sprint; `sprint start` activates exactly one sprint"
tests = ["/test_S04_(new|start)_/"]

[[ac]]
id    = "AC2"
desc  = "The gate computes AC state from passing tests and labels regressions from closed sprints"
tests = ["/test_S04_gate_/"]

[[ac]]
id    = "AC3"
desc  = "`sprint close` (human) requires a passing gate on a clean HEAD and every AC satisfied, then baselines, tags and updates CHANGELOG"
tests = ["/test_S04_close_/"]

[[ac]]
id    = "AC4"
desc  = "`sprint status` shows the sprint, AC states and regressions per sprint; `sprint note` records decisions"
tests = ["/test_S04_(status|note)_/"]

[[ac]]
id    = "AC5"
desc  = "A multi-sprint lifecycle works end to end"
tests = ["test_S04_full_lifecycle_across_sprints"]
+++

## Notes / decisions
- 2026-10-12: lifecycle commands were written during S03 (the MCP note tool needs them); S04 adds their tests and polish (agent: claude-code)
