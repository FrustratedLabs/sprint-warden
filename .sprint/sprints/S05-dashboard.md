+++
id      = "S05"
title   = "Dashboard"
status  = "active"          # planned | active | closed
goal    = "One local, read-only portfolio dashboard across every registered project"
started = 2026-10-12
closed  = ""
out_of_scope = ["editing sprint files from the UI", "hosted server"]

[[ac]]
id    = "AC1"
desc  = "Registry-backed read-only JSON API: /api/projects, /api/projects/<key>, /api/projects/<key>/runs"
tests = ["/test_S05_api_/"]

[[ac]]
id    = "AC2"
desc  = "Portfolio status is correct: pass, fail, stale (run older than HEAD), none, error; failing first"
tests = ["/test_S05_portfolio_/"]

[[ac]]
id    = "AC3"
desc  = "Localhost-only and read-only: Host check, no writes, no path traversal"
tests = ["/test_S05_security_/"]

[[ac]]
id    = "AC4"
desc  = "The five views render in a real browser (portfolio, timeline, matrix, trends, run detail)"
tests = ["test_S05_browser_views_render_in_headless_chrome"]    # the Playwright variant runs in the CI browser job
+++

## Notes / decisions
- 2026-10-12: AC4 targets the headless-Chrome render test; the Playwright variant only runs in the CI browser job (permanent skip allowance, D-021) (agent: claude-code)
