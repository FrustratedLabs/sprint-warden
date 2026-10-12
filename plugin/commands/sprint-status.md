---
description: Show this project's sprintwarden status (active sprint, ACs, last gate, baseline)
allowed-tools: Bash(sprint status:*), Bash(sprint gate:*), Bash(sprint history:*)
---

Current sprintwarden status for this project:

!`sprint status 2>&1 || echo "(sprintwarden is not set up here: run 'sprint init --ratchet-only')"`

Summarize it in a few lines: the active sprint and its goal, which acceptance
criteria are not yet satisfied, and whether the last gate passed. If the last
gate is stale or failing, offer to run `sprint gate`. Do not run human-only
commands (`sprint close`, `sprint baseline`, `sprint accept-removal`,
`sprint allow-skip`).
