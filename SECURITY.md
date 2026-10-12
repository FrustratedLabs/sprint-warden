# Security policy

## Supported versions

The latest minor release receives fixes.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability). Don't open a public issue. We aim to
acknowledge reports within a week.

## Threat model (what sprintwarden is and isn't)

- **It runs your test command.** `.sprint/config.toml` contains a shell command that
  `sprint gate`, the git pre-push hook and the agent hooks execute. Treat changes to
  that file in pull requests like changes to a CI script.
- **The human-only guard is a speed bump, not security.** Agent detection reads
  environment variables, which any process can set or unset, and `--i-am-human`
  exists. The real authority is CI (`--baseline-ref` compares against the main
  branch's committed baseline) plus code review of `.sprint/` changes.
- **No network, no telemetry.** The CLI never makes network requests. The
  dashboard (`sprint ui`) binds to 127.0.0.1, is read-only, and rejects requests
  whose `Host` header isn't localhost (DNS-rebinding protection).
- **Parsing.** JUnit XML is parsed with the standard library's expat-based parser,
  which since Python 3.7.1/expat 2.4 limits entity expansion ("billion laughs").
  External entities are not resolved.
