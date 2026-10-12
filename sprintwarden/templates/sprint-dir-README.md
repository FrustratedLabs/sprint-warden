# .sprint/ — managed by sprintwarden

This folder is the source of truth for the test ratchet (and sprints, if enabled).
Everything here is plain text; review changes to it like code.

| file | what it is | who edits it |
|---|---|---|
| `config.toml` | test command, report globs, settings | humans |
| `sprints/*.md` | sprint goal + acceptance criteria (TOML front matter) | humans; agents only append notes via `sprint note` |
| `baseline.json` | the ratchet: every test that must keep existing and passing | `sprint baseline` / `sprint close` (human-only) |
| `removals.json` | tests a human accepted as intentionally removed, with reasons | `sprint accept-removal` (human-only) |
| `skips.json` | tests a human allowed to be skipped, with reasons | `sprint allow-skip` (human-only) |
| `runs/` | one JSON record per gate run (history) | `sprint gate` |
| `latest.json` | the most recent gate run | `sprint gate` |
| `out/` | raw reports, logs, hook state (gitignored) | `sprint gate` |

A shrinking `baseline.json` or new entries in `removals.json`/`skips.json` in a
pull request deserve a close look. See https://github.com/sprintwarden/sprintwarden.
