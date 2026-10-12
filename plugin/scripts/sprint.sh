#!/bin/sh
# Runs the sprintwarden CLI for the plugin's hooks. Every hook exits 0 at once in
# repos without a .sprint/ folder, and the PreToolUse guard does nothing unless
# [hooks] claude_pretool_guard = true in .sprint/config.toml.
if command -v sprint >/dev/null 2>&1; then exec sprint "$@"; fi
if command -v sprintwarden >/dev/null 2>&1; then exec sprintwarden "$@"; fi
if command -v uvx >/dev/null 2>&1; then exec uvx --quiet --from sprintwarden sprint "$@"; fi
# Not installed: never block the session, just say so once per run.
if [ -d .sprint ]; then
  echo "sprintwarden plugin: the 'sprint' CLI is not installed. Run: pipx install sprintwarden" >&2
fi
exit 0
