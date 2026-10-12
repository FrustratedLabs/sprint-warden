#!/bin/sh
# The README demo: an agent "fixes" a failing build by deleting an old test,
# and `sprint gate` blocks it. Needs `sprint` and `pytest` on PATH.
# Render: python docs/make_demo_svg.py  (or `vhs docs/demo.tape` for a GIF)
set -e
export NO_COLOR=1 SPRINT_AGENT=human SPRINT_HOME="${SPRINT_HOME:-$(mktemp -d)}"
dir=$(mktemp -d)/invoices && mkdir -p "$dir/tests" && cd "$dir"
git init -q -b main && git config user.email demo@example.invalid && git config user.name demo
cat > app.py <<'PY'
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: str) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def with_vat(cents: int, rate: str) -> int:
    return int((cents * (1 + Decimal(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
PY
cat > tests/test_invoice.py <<'PY'
from app import to_cents, with_vat


def test_S01_rounds_half_up():
    assert to_cents("1.005") == 101


def test_S01_whole_amounts():
    assert to_cents("12") == 1200


def test_S02_adds_vat():
    assert with_vat(1000, "0.20") == 1200


def test_health():
    assert True
PY
printf '[pytest]\npythonpath = .\n' > pytest.ini
git add -A && git commit -qm "invoices"

say() { printf '\n# %s\n' "$*"; }
# run "<shown command>" ["<actual command>"]: the demo shows clean commands
run() { printf '$ %s\n' "$1"; sh -c "${2:-$1}" 2>&1 || true; }

say "Protect every test that exists today (2 minutes, any stack):"
run "sprint init --ratchet-only" "sprint init --ratchet-only --no-hooks --yes | grep -E 'stack|baseline written'"
git add -A && git commit -qm "add sprintwarden"

say "An agent refactors to_cents() with float maths and breaks rounding..."
python3 - <<'PY'
import pathlib
p = pathlib.Path("app.py")
lines = p.read_text().splitlines(keepends=True)
lines[4] = "    return round(float(amount) * 100)\n"
p.write_text("".join(lines))
PY
run "sprint gate"

say "...then 'fixes' the red build by deleting the old test:"
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("tests/test_invoice.py")
p.write_text(re.sub(r"def test_S01_rounds_half_up\(\):\n    assert .*\n\n\n", "", p.read_text()))
PY
run "pytest -q" "python3 -m pytest -q -p no:cacheprovider 2>&1 | tail -1"
run "sprint gate"
say "Only a human can accept that: sprint accept-removal <test> --reason '...'"
