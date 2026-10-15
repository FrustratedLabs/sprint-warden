"""Build a synthetic demo portfolio and screenshot the dashboard with headless Chrome.

    python docs/make_screenshots.py            # writes docs/dashboard*.png
    python docs/make_screenshots.py --serve    # just build the demo and serve it

Everything happens in a temporary SPRINT_HOME, so your real registry is untouched.
All names and data are made up.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tests.helpers import FakeProject, T  # noqa: E402

DOCS = REPO / "docs"


def sprint_file(p: FakeProject, sid: str) -> Path:
    return next((p.root / ".sprint" / "sprints").glob(f"{sid}-*.md"))


def edit(p: FakeProject, sid: str, **replace: str) -> None:
    path = sprint_file(p, sid)
    text = path.read_text(encoding="utf-8")
    for old, new in replace.items():
        text = text.replace(old.replace("_", " ") if old.startswith("__") else old, new)
    path.write_text(text, encoding="utf-8")


def set_acs(p: FakeProject, sid: str, acs: list[tuple[str, str]], note: str = "") -> None:
    path = sprint_file(p, sid)
    text = path.read_text(encoding="utf-8")
    start = text.index("[[ac]]")
    end = text.index("+++", start)
    block = "".join(
        f'[[ac]]\nid    = "AC{i}"\ndesc  = "{desc}"\ntests = ["{pattern}"]\n\n'
        for i, (desc, pattern) in enumerate(acs, 1)
    )
    text = text[:start] + block + text[end:]
    if note:
        text += f"- 2026-10-08: {note}\n"
    path.write_text(text, encoding="utf-8")


def gate(p: FakeProject, tests: list[dict], agent: str = "claude-code", n: int = 1) -> None:
    p.scenario(tests)
    for _ in range(n):
        p.sprint("gate", agent=agent)
        time.sleep(0.02)


def close(p: FakeProject, sid: str, tests: list[dict]) -> None:
    gate(p, tests)
    p.commit(f"{sid} done")
    r = p.sprint("close", sid)
    assert r.code == 0, r.out + r.err


def build(root: Path, home: Path) -> None:
    # billing-service: a long-running product with sprints in every column
    b = FakeProject(root / "billing-service", home)
    b.init(
        "--no-hooks",
        "--key",
        "BILL",
        "--sprint-title",
        "Sign-in",
        tests=[T("HealthTest", "healthCheck")],
    )
    set_acs(
        b,
        "S01",
        [
            ("Users sign in with email and password", "S01_signIn"),
            ("Lockout after 5 failed attempts", "S01_lockout"),
        ],
        "chose **argon2id** for password hashing (agent: claude-code)",
    )
    edit(
        b,
        "S01",
        **{'goal    = ""': 'goal    = "Customers can sign in, and brute force gets locked out"'},
    )
    t1 = [
        T("HealthTest", "healthCheck"),
        T("AuthTest", "S01_signIn"),
        T("AuthTest", "S01_lockoutAfter5Attempts"),
    ]
    close(b, "S01", t1)

    plan = [
        ("Invoices", "Invoices total correctly and round half-up to the cent"),
        ("Payment retries", "Failed card payments retry on a backoff schedule"),
        ("Tax rules", "Invoices apply regional tax rates"),
        ("PDF export", "Customers download any invoice as a PDF"),
        ("Dunning emails", "Overdue invoices trigger reminder emails"),
        ("Multi-currency", "Prices and invoices in EUR, GBP and INR"),
    ]
    for title, goal in plan:
        b.sprint("new", title, "--goal", goal)
    b.sprint("start", "S02")
    set_acs(
        b,
        "S02",
        [
            ("Line items sum to the invoice total", "S02_total"),
            ("Totals round half-up to the cent", "S02_rounds"),
        ],
        "used `Decimal` with ROUND_HALF_UP instead of floats (agent: claude-code)",
    )
    t2 = t1 + [T("InvoiceTest", "S02_totalSumsLineItems"), T("InvoiceTest", "S02_roundsHalfUp")]
    close(b, "S02", t2)

    b.sprint("start", "S03")
    set_acs(
        b,
        "S03",
        [
            ("A failed charge retries after 1h, 6h and 24h", "S03_retrySchedule"),
            ("After the last retry the invoice is marked unpaid", "S03_marksUnpaid"),
            ("Retries are idempotent per charge", "S03_idempotent"),
        ],
        "retry timing lives in config, not code (agent: claude-code)",
    )
    edit(
        b, "S03", **{"out_of_scope = []": 'out_of_scope = ["SMS notifications", "partial refunds"]'}
    )
    set_acs(
        b, "S04", [("EU VAT by country", "S04_euVat"), ("US sales tax by state", "S04_usSalesTax")]
    )
    set_acs(
        b,
        "S05",
        [
            ("Any invoice downloads as a PDF", "S05_pdf"),
            ("PDFs carry the company logo", "S05_logo"),
        ],
    )
    set_acs(b, "S06", [("Reminder 3 days after the due date", "S06_reminder")])
    set_acs(
        b,
        "S07",
        [
            ("Prices shown in the customer's currency", "S07_display"),
            ("Invoices total in one currency", "S07_singleCurrency"),
        ],
    )
    b.sprint("park", "S06", "--reason", "waiting on the email provider contract")
    b.sprint("park", "S07", "--reason", "not this quarter")
    b.commit("plan")
    t3 = t2 + [
        T("RetryTest", "S03_retrySchedule"),
        T("RetryTest", "S03_marksUnpaid", "failed", "expected UNPAID but was PENDING"),
        T("RetryTest", "S03_idempotentPerCharge"),
    ]
    gate(b, t3, n=2)
    broken = [dict(t) for t in t3]
    broken[4] = T("InvoiceTest", "S02_roundsHalfUp", "failed", "expected 1.01 but was 1.00")
    gate(b, broken)

    # storefront: sprints mode, everything green
    s = FakeProject(root / "storefront", home)
    s.init(
        "--no-hooks",
        "--key",
        "SHOP",
        "--sprint-title",
        "Catalogue",
        tests=[T("HomeTest", "rendersHome")],
    )
    set_acs(s, "S01", [("Products list with filters", "S01_productList")])
    close(s, "S01", [T("HomeTest", "rendersHome"), T("CatalogueTest", "S01_productListFilters")])
    for title, goal in [
        ("Cart", "Customers add, remove and update items in a cart"),
        ("Checkout", "Guest checkout with card payments"),
        ("Wishlists", "Signed-in customers save items for later"),
    ]:
        s.sprint("new", title, "--goal", goal)
    s.sprint("start", "S02")
    set_acs(
        s,
        "S02",
        [
            ("Add and remove items", "S02_addRemove"),
            ("Quantities update the total", "S02_quantity"),
        ],
    )
    set_acs(
        s,
        "S03",
        [("Guest checkout without an account", "S03_guest"), ("Card payments", "S03_card")],
    )
    set_acs(s, "S04", [("Save an item for later", "S04_save")])
    s.sprint("park", "S04", "--reason", "after launch")
    s.commit("plan")
    gate(
        s,
        [
            T("HomeTest", "rendersHome"),
            T("CatalogueTest", "S01_productListFilters"),
            T("CartTest", "S02_addRemoveItems"),
            T("CartTest", "S02_quantityUpdatesTotal"),
        ],
        agent="cursor",
        n=3,
    )

    # mobile-app and docs-site: ratchet only
    m = FakeProject(root / "mobile-app", home)
    m.init(
        "--ratchet-only",
        "--no-hooks",
        "--key",
        "MOB",
        tests=[
            T("LoginScreenTest", "showsErrors"),
            T("FeedTest", "loadsMore"),
            T("ProfileTest", "editsName"),
        ],
    )
    m.commit("setup")
    m.sprint("gate", agent="codex")
    m.commit("more work")
    w = FakeProject(root / "docs-site", home)
    w.init(
        "--ratchet-only",
        "--no-hooks",
        "--key",
        "DOCS",
        tests=[T("LinksTest", "noBrokenLinks"), T("BuildTest", "builds")],
    )
    w.commit("setup")
    gate(w, [T("LinksTest", "noBrokenLinks"), T("BuildTest", "builds")], agent="human", n=2)


def chrome() -> str:
    for c in (
        os.environ.get("CHROME_BIN"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if c and os.path.exists(c):
            return c
    sys.exit("needs Chrome or Chromium (set CHROME_BIN)")


def shoot(url: str, out: Path, size: str, profile: Path, dark: bool = False) -> None:
    # Blink's preferredColorScheme: 0 = dark, 1 = light (otherwise it follows the OS)
    args = [
        chrome(),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        f"--user-data-dir={profile}",
        f"--window-size={size}",
        "--virtual-time-budget=4000",
        "--force-device-scale-factor=2",
        f"--blink-settings=preferredColorScheme={0 if dark else 1}",
        f"--screenshot={out}",
        url,
    ]
    subprocess.run(args, capture_output=True, timeout=90, check=False)
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--serve", action="store_true", help="serve the demo instead of taking screenshots"
    )
    ap.add_argument("--out", type=Path, default=DOCS)
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="sprintwarden-demo-"))
    home = work / "home"
    os.environ["SPRINT_HOME"] = str(home)
    os.environ.pop("CLAUDECODE", None)
    build(work / "projects", home)
    from sprintwarden.ui.server import serve_in_thread

    server, _ = serve_in_thread(0)
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    if args.serve:
        print(f"demo dashboard: {base}  (SPRINT_HOME={home}; Ctrl+C to stop)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    profile = work / "chrome"
    shots = [
        ("#/", "dashboard.png", "1440,900"),
        ("#/board", "dashboard-board.png", "1440,1000"),
        ("#/p/BILL/board/S03", "dashboard-sprint.png", "1440,1000"),
        ("#/p/BILL/matrix", "dashboard-matrix.png", "1440,620"),
        ("#/p/BILL/trends", "dashboard-trends.png", "1440,1480"),
    ]
    for route, name, size in shots:
        shoot(base + route, args.out / name, size, profile)
    shoot(base + "#/board", args.out / "dashboard-board-dark.png", "1440,1000", profile, dark=True)
    server.shutdown()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
