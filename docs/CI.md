# CI

CI is the final authority: agents can edit any file locally, but CI checks the
branch against the baseline committed on the main branch.

## GitHub Actions

```yaml
name: sprintwarden
on: [pull_request, push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4          # whatever your tests need
        with: { distribution: temurin, java-version: "21" }
      - uses: FrustratedLabs/sprint-warden@v0
```

The action installs sprintwarden, runs `sprint gate --json`, writes a **job
summary** (checks table, failing tests with REGRESSION labels, missing tests, new
skips, ACs, and any removals/skips accepted on the branch), adds error
**annotations**, uploads `latest.json` + the JUnit XML as an artifact, and fails
the job on gate failure.

| input | default | |
|---|---|---|
| `working-directory` | `.` | directory containing `.sprint/` |
| `args` | | extra `sprint gate` args, e.g. `--no-run` if an earlier step ran the tests |
| `baseline-ref` | `auto` | `auto` = the PR's base branch; a ref like `origin/main`; or `none` |
| `python-version` / `setup-python` | `3.12` / `true` | Python used to run sprintwarden |
| `version` | | PyPI version; empty = the action's own source |
| `upload-artifacts` / `artifact-name` | `true` / `sprintwarden-gate` | |

Outputs: `result` (`pass`/`fail`), `regressions`, `missing`.

Already running tests in another step? Point the reports at the same place and
pass `args: --no-run`.

## GitLab CI, Jenkins, anything else

Copy `sprintwarden/templates/ci/sprint-gate.sh` (installed with the package, or from
this repository) into your repo, then:

- **GitLab**: see `templates/ci/gitlab-ci.yml`. It sets `BASELINE_REF` to the merge
  request's target branch and publishes the XML as a JUnit report.
- **Jenkins**: see `templates/ci/Jenkinsfile`. It uses `CHANGE_TARGET` for pull requests.
- **Generic**: `BASELINE_REF=origin/main sh sprint-gate.sh`. Exit code 1 means the
  gate failed; `.sprint/out/artifacts/summary.md` has a markdown summary.

## Why `--baseline-ref`?

Without it, a branch could delete a test *and* remove it from `.sprint/baseline.json`
in the same commit, and the local gate would pass. With `--baseline-ref origin/main`
the gate loads the baseline from the main branch instead. Acceptances
(`removals.json`, `skips.json`) are still read from the branch, because a human may
legitimately accept a removal in the PR, and they are listed under "Exceptions
accepted on this branch" in the summary so reviewers see them.
