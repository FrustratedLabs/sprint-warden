+++
id      = "S07"
title   = "Sprint board and dashboard refresh"
status  = "closed"          # planned | active | closed
goal    = "See what is planned, in progress, done and parked on a kanban board, in a refreshed dashboard with Lucide icons"
started = 2026-10-12
closed  = 2026-10-15
out_of_scope = ["editing sprints from the UI (the dashboard stays read-only)", "drag and drop", "Phase 7 integrations"]

[[ac]]
id    = "AC1"
desc  = "A sprint can be parked and brought back: `sprint park` / `sprint unpark`, `start` works from parked, status and doctor understand it"
tests = ["/test_S07_park/"]

[[ac]]
id    = "AC2"
desc  = "The API gives every sprint its board data: test counts, regressed flag for done sprints, up-next marker"
tests = ["/test_S07_api_board/"]

[[ac]]
id    = "AC3"
desc  = "Each project has a Board view with Planned / In progress / Done / Parked columns and a sprint detail panel"
tests = ["/test_S07_board_/"]

[[ac]]
id    = "AC4"
desc  = "One board across all registered projects"
tests = ["/test_S07_all_projects_board/"]

[[ac]]
id    = "AC5"
desc  = "Refreshed design with vendored Lucide icons: no network, license notice shipped, the five S05 views still render"
tests = ["/test_S07_(icons|design)_/"]
+++

## Notes / decisions
- 2026-10-12: Board is read-only and moves happen in the CLI; parked is a fourth sprint status; Lucide icons vendored as data; Sprints stays the default project tab because an S05 test pins it (docs/DECISIONS.md D-023 to D-026) (agent: claude-code)
- 2026-10-14: All dashboard status marks are Lucide icons next to a word (human chose Lucide everywhere; S05 pill checks updated with their OK); board gets a Full/Compact card switch; Trends is two single-axis charts with plain-language findings (docs/DECISIONS.md D-028 to D-030) (agent: claude-code)
