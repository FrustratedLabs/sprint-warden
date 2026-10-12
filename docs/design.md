# Design

## Principles

1. **The repo is the source of truth.** All state is plain files under `.sprint/`.
   No database, no server.
2. **Stack agnosticism via JUnit XML.** sprintwarden runs a configured shell command
   and parses the XML it leaves; the only stack-specific file is `config.toml`.
3. **Sprint attribution by test name.** `S03_exportsPdf` belongs to S03. The gate
   always runs the full suite and attributes results while parsing.
4. **"Done" is computed.** An AC is satisfied only when its tests exist and pass in
   the latest gate run.
5. **Ratchet: tests only go up.** A baseline test must still exist and pass, or be
   explicitly accepted as removed by a human, with a reason. New skips fail.
6. **Layered adoption.** Ratchet-only mode works without sprint files; sprints, ACs,
   hooks, CI and the dashboard are opt-in layers.
7. **One CLI, many consumers.** Agent hooks, git hooks, CI and the UI all call or
   read the same CLI and JSON.
8. **Zero runtime dependencies.** Python 3.11+ standard library.
9. **Cross-platform.** Hooks are Python entry points (git hooks are a 5-line `sh`
   shim, which Git for Windows runs too).
10. **No telemetry.**

## Data flow

```
                ┌────────────── sprint gate ──────────────┐
config.toml ──► │ clean stale XML → run command(s) → parse │──► runs/YYYY-MM/<id>.json
sprints/*.md ─► │ attribute → evaluate checks              │──► latest.json (+ acs_all)
baseline.json ► │                                          │──► out/latest-full.json
removals/skips ►└──────────────────────────────────────────┘          │
                         ▲            ▲            ▲                   ▼
                    Stop hook     pre-push      CI action         sprint ui / status
```

## Files

| path | written by | committed |
|---|---|---|
| `.sprint/config.toml` | `init`, `start`, `close` (one value at a time, comments kept) | yes |
| `.sprint/sprints/Sxx-*.md` | humans; `new`/`start`/`close`/`note` edit single fields | yes |
| `.sprint/baseline.json` | `init`, `baseline`, `close`: `{tests: {id: "passed"\|"skipped"}}`, sorted, one per line | yes |
| `.sprint/removals.json`, `skips.json` | `accept-removal`, `allow-skip`: `{id, reason, by, at, git_head}` | yes |
| `.sprint/runs/YYYY-MM/<id>.json` | every gate run (lists capped at 200) | yes (`[history] in_git`) |
| `.sprint/latest.json` | every gate run: the run record + `acs_all` | yes |
| `.sprint/out/` | raw XML, `runner.log`, `latest-full.json`, `hook-state.json`, `gate.lock` | no |
| `~/.sprintwarden/registry.toml` | `init`, `register` | n/a |

### Run record (`schema: 1`)

```json
{
  "schema": 1, "id": "20261012T103105123Z-3fa2", "project": "billing-service", "key": "BILL",
  "mode": "sprints", "sprint": "S03", "sprint_title": "Reports", "timestamp": "2026-10-12T10:31:05Z",
  "git": { "head": "abc123…", "branch": "feat/reports", "dirty": false, "fingerprint": "…" },
  "agent": "claude-code", "trigger": "hook:claude-stop", "bypassed": false, "ran": true,
  "duration_s": 38.2, "result": "fail",
  "checks": [{ "id": "failures", "ok": false, "blocking": true, "summary": "2 failing (1 regression)", "detail": "" }],
  "totals": { "total": 412, "passed": 408, "failed": 2, "skipped": 2 },
  "by_sprint": { "legacy": { "total": 40, "passed": 40, "failed": 0, "skipped": 0 }, "S01": {} },
  "acs": [{ "sprint": "S03", "id": "AC1", "desc": "…", "satisfied": false, "state": "failing", "tests": [{ "id": "…", "outcome": "failed" }] }],
  "failing": [{ "id": "AuthTest.S01_lockoutAfter5Attempts", "sprint": "S01", "regression": true,
                "regression_reason": "from sprint S01", "message": "first 500 chars" }],
  "new_skips": [], "missing": [],
  "counts": { "failing": 2, "regressions": 1, "missing": 0, "new_skips": 0, "new_tests": 14, "flaky": 0 },
  "baseline": { "created": "…", "reason": "close S02", "total": 398, "ref": null },
  "runner": [{ "suite": "default", "command": "./gradlew test", "exit_code": 1, "duration_s": 37.9, "timed_out": false }],
  "milestone": null, "version": "0.2.0"
}
```

`ok` is `true`, `false`, or `null` (not evaluated, e.g. no results). Non-blocking
checks (ACs; `missing`/`skips` when their `fail_on_*` flag is off) don't affect
`result`.

## Regressions

A failing test is labelled a **regression** when it passed in the baseline, or (in
sprints mode) when it belongs to a closed sprint or a sprint numbered below the
current one. The label says which sprint it came from.

## Extending checks

Checks are functions `(Context, Evaluation) -> Check | None` in
`sprintwarden.gate.CHECKS`. A coverage check (Cobertura/LCOV) would read its report
in `collect`, add a field to `Context`, and append a function; nothing else in the
record format changes.

## Concurrency and long-lived projects

- One gate per working tree (`out/gate.lock`, stale locks from dead processes are
  ignored). Separate git worktrees are independent.
- Run ids sort chronologically to the millisecond; history is sharded by month;
  `[history] keep` prunes old runs but never milestones.
- Sprint ids sort numerically (S99 < S100).
- AC matching joins all test ids into one string and scans with `str.find` /
  `re.finditer`, so hundreds of ACs over tens of thousands of tests stay fast.
