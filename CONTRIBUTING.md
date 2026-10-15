# Contributing to sprintwarden

Thanks for helping! Bug reports, new stack templates and agent integrations are
especially welcome.

## Ground rules

- **Runtime code is standard-library only** (Python 3.11+). Dev tools (pytest, ruff)
  are fine. This keeps `pipx install sprintwarden` instant and auditable.
- **The repo is the source of truth.** Everything sprintwarden stores is a plain
  file under `.sprint/`. No databases, no network calls, no telemetry.
- **Cross-platform.** macOS, Linux and Windows. Hooks are Python entry points; no
  bash-only logic.
- Record any non-obvious design choice in `docs/DECISIONS.md`.

## Development setup

```sh
git clone https://github.com/FrustratedLabs/sprint-warden && cd sprint-warden
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e . pytest ruff
python -m pytest -q
ruff check . && ruff format --check .
```

## We dogfood sprintwarden

This repository is tracked with sprintwarden itself (`.sprint/`). Before you open
a pull request:

1. `sprint status` shows the active sprint. Name new tests after it:
   `def test_S04_close_requires_all_acs():`.
2. `sprint gate` must pass. It runs the whole suite and fails if any test that
   existed before was deleted, skipped or broken.
3. Don't edit `.sprint/baseline.json`, `removals.json` or `skips.json` by hand.
   If a test really must go, say why in the PR; a maintainer runs
   `sprint accept-removal`.

CI runs the same gate with the repository's own GitHub Action (`uses: ./`).

## Adding a stack

Usually a single TOML file in `sprintwarden/templates/stacks/` plus a real
(sanitized) JUnit XML fixture. See [docs/ADDING_A_STACK.md](docs/ADDING_A_STACK.md).

## Commit messages and releases

- Short imperative subject; explain *why* in the body.
- Versioning is semantic. Maintainers tag `vX.Y.Z`; the release workflow publishes
  to PyPI via trusted publishing and moves the `vX` tag used by the GitHub Action.
- Update `CHANGELOG.md` (Keep a Changelog format) under `[Unreleased]`.

By contributing you agree that your contributions are licensed under the MIT
License, and to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
