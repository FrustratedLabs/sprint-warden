# Setting up agents

sprintwarden needs no agent-specific code: every agent that can read `AGENTS.md`
and run a shell command can follow the workflow, and the git pre-push hook plus CI
catch the ones that don't. Agent hooks add an earlier, tighter loop.

| agent | rules file | "can't finish while the gate fails" | status |
|---|---|---|---|
| Claude Code | `CLAUDE.md` → `@AGENTS.md` | Stop hook (`sprint gate --hook`) | supported, tested |
| Cursor | `AGENTS.md` (native) | `stop` hook → `followup_message` | experimental |
| OpenAI Codex | `AGENTS.md` (native) | `Stop` hook → `decision: block` | experimental |
| Gemini CLI | `GEMINI.md`; we add `AGENTS.md` to `context.fileName` | `AfterAgent` hook → `decision: deny` | experimental |
| GitHub Copilot (CLI / cloud agent) | `AGENTS.md` (native) | `agentStop` hook → `decision: block` | experimental |
| Windsurf, Jules, Amp, OpenCode, Goose, Kiro, Zed, Warp, … | `AGENTS.md` (native) | none: pre-push + CI | rules only |
| Aider | add `read: AGENTS.md` to `.aider.conf.yml` | none: pre-push + CI | rules only |

"Experimental" means the hook contract comes from that agent's docs (as of
October 2026) and is covered by our tests, but those hook APIs are young and change
often. Please report breakage.

## Claude Code

`sprint init` merges three hooks into `.claude/settings.json` (existing hooks are
kept; re-running is a no-op):

```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "sprint gate --hook", "timeout": 1800 }] }],
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "sprint hook session-start", "timeout": 30 }] }]
  }
}
```

- **Stop**: if the tree changed since the last gate, run it; on failure, exit 2 with
  a compact report on stderr (regressions first, then failing, missing and newly
  skipped tests) and "Fix these; do not delete or skip tests". After
  `stop_hook_max_blocks` (default 3) consecutive blocks in one turn, the agent is
  allowed to stop and you get a `systemMessage`.
- **SessionStart**: prints the active sprint, ACs and last gate result into the
  context, so a new, resumed or compacted session starts from the real state.
- **PreToolUse guard** (opt-in: `sprint init --with-guard` or
  `[hooks] claude_pretool_guard = true`): warns when an edit removes test
  functions or adds skip/focus markers (`@Disabled`, `pytest.mark.skip`, `.skip(`,
  `.only(`, `xit(`, `t.Skip(`, `#[ignore]`, …), and asks you before an agent edits
  `.sprint/` state, deletes test files, runs a human-only command or passes
  `--i-am-human`. `pretool_mode = "block"` denies instead of warning.

Prefer a plugin? See the README ("Claude Code plugin"). Don't install both the
plugin and the project hooks; it works, but the hook runs twice.

## Cursor, Codex, Gemini CLI, Copilot

```sh
sprint install-hooks --agent cursor     # .cursor/hooks.json        (stop)
sprint install-hooks --agent codex      # .codex/hooks.json         (Stop; trust it via /hooks)
sprint install-hooks --agent gemini     # .gemini/settings.json     (AfterAgent + context.fileName)
sprint install-hooks --agent copilot    # .github/hooks/sprintwarden.json (agentStop)
```

Or all at once during setup: `sprint init --agents cursor,codex,gemini,copilot`.
Every hook shares the Stop hook's logic (change detection, failure replay, loop
guard). Most of these agents also cap consecutive blocks on their side.

## MCP (any client)

`sprint mcp` is a stdio MCP server with `sprint_status`, `sprint_gate`,
`sprint_history` and `sprint_note`. Human-only commands are not exposed.

```sh
claude mcp add sprintwarden -- sprint mcp                      # Claude Code
codex mcp add sprintwarden -- sprint mcp                       # Codex
gemini mcp add sprintwarden sprint mcp                         # Gemini CLI
```

Cursor (`.cursor/mcp.json`):

```json
{ "mcpServers": { "sprintwarden": { "command": "sprint", "args": ["mcp"] } } }
```

## How agents are detected

Used for the `agent` field of run records and the human-only guard. Checked in
order: `SPRINT_AGENT` (override), `AI_AGENT` (emerging cross-agent convention, e.g.
`claude-code_2-1-296_agent`), per-agent variables (`CLAUDECODE`,
`CLAUDE_CODE_CHILD_SESSION`, `CURSOR_AGENT`, `CODEX_SANDBOX`/`CODEX_CI`/`CODEX_THREAD_ID`,
`GEMINI_CLI`, `ANTIGRAVITY_AGENT`, `COPILOT_AGENT_*`, `CLINE_ACTIVE`, `OPENCODE`, …),
the legacy `AGENT` variable, then CI (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, …).

Humans working in an agent's integrated terminal can be detected as the agent
(some IDE extensions set `CLAUDECODE=1` in every terminal). Pass `--i-am-human` or
set `SPRINT_AGENT=human`.
