#!/bin/sh
# Generic CI step for sprintwarden (GitLab CI, Jenkins, Buildkite, CircleCI, ...).
# Usage: sh sprint-gate.sh [extra `sprint gate` args]
# Env:   BASELINE_REF  git ref whose committed baseline is the authority, e.g.
#                      origin/main on merge requests (fetched if missing). Optional.
set -u
python -m pip install --disable-pip-version-check -q "sprintwarden${SPRINTWARDEN_VERSION:+==$SPRINTWARDEN_VERSION}"
set -- gate --trigger ci --collect-reports .sprint/out/artifacts "$@"
if [ -n "${BASELINE_REF:-}" ]; then
  branch="${BASELINE_REF#origin/}"
  git fetch --no-tags --depth=1 origin "+refs/heads/$branch:refs/remotes/origin/$branch" >/dev/null 2>&1 || true
  set -- "$@" --baseline-ref "$BASELINE_REF"
fi
sprint "$@"
code=$?
mkdir -p .sprint/out/artifacts
sprint export --format markdown > .sprint/out/artifacts/summary.md 2>/dev/null || true
exit $code
