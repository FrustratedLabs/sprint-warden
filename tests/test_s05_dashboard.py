"""Phase 5: the local dashboard (registry, read-only API, views)."""

from __future__ import annotations

import http.client
import json
import os
import shutil

import pytest

from sprintwarden import registry
from sprintwarden.ui.server import serve_in_thread
from tests.helpers import BASE_TESTS, FakeProject, T

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Four registered projects: failing (sprints), passing, stale, broken config."""
    home = tmp_path_factory.mktemp("ui-home")
    root = tmp_path_factory.mktemp("ui-projects")
    old = os.environ.get("SPRINT_HOME")
    os.environ["SPRINT_HOME"] = str(home)

    bill = FakeProject(root / "billing", home)
    assert (
        bill.init("--no-hooks", "--key", "BILL", "--sprint-title", "Auth", tests=BASE_TESTS).code
        == 0
    )
    s01 = next((bill.root / ".sprint" / "sprints").glob("S01-*.md"))
    s01.write_text(
        s01.read_text().replace("tests = []", 'tests = ["S01_login"]')
        + "- 2026-10-12: chose **bcrypt** (agent: codex)\n"
    )
    bill.commit("s01")
    bill.sprint("gate")
    broken = [dict(t) for t in BASE_TESTS]
    broken[1] = T("AuthTest", "S01_lockoutAfter5Attempts", "failed", "expected 423 but was 200")
    bill.scenario(broken[:-1])
    bill.sprint("gate", agent="claude-code")

    web = FakeProject(root / "web", home)
    assert web.init("--ratchet-only", "--no-hooks", "--key", "WEB").code == 0
    web.commit("setup")
    web.sprint("gate")

    stale = FakeProject(root / "mobile", home)
    assert stale.init("--ratchet-only", "--no-hooks", "--key", "MOB").code == 0
    stale.commit("setup")
    stale.sprint("gate")
    stale.commit("moved on")

    bad = FakeProject(root / "broken", home)
    assert bad.init("--ratchet-only", "--no-hooks", "--no-gate", "--key", "BAD").code == 0
    (bad.root / ".sprint" / "config.toml").write_text("[test\n")
    registry.register(root / "gone")  # registered, then deleted

    # a second project with a clashing key
    dup = FakeProject(root / "web2", home)
    assert dup.init("--ratchet-only", "--no-hooks", "--no-gate", "--key", "WEB").code == 0

    server, _ = serve_in_thread(0)
    port = server.server_address[1]
    yield {"port": port, "bill": bill, "home": home}
    server.shutdown()
    server.server_close()
    if old is None:
        os.environ.pop("SPRINT_HOME", None)
    else:
        os.environ["SPRINT_HOME"] = old


def get(world, path, *, host=None, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", world["port"], timeout=10)
    conn.request(method, path, headers={"Host": host or f"127.0.0.1:{world['port']}"})
    res = conn.getresponse()
    body = res.read()
    conn.close()
    ctype = res.getheader("Content-Type", "")
    data = json.loads(body) if "json" in ctype else body
    return res.status, data, res


@pytest.fixture(autouse=True)
def _keep_world_home(world, monkeypatch):
    monkeypatch.setenv("SPRINT_HOME", str(world["home"]))


# --------------------------------------------------------------------------- API


def test_S05_api_projects_lists_every_registered_project(world):
    status, data, _ = get(world, "/api/projects")
    assert status == 200 and data["version"]
    keys = [p["key"] for p in data["projects"]]
    assert set(keys) == {"BILL", "WEB", "WEB-2", "MOB", "broken", "gone"}
    bill = next(p for p in data["projects"] if p["key"] == "BILL")
    assert bill["mode"] == "sprints" and bill["sprint"]["id"] == "S01"
    assert bill["acs"] == {"satisfied": 1, "total": 1}
    assert bill["latest"]["counts"]["regressions"] == 1 and bill["latest"]["agent"] == "claude-code"


def test_S05_api_project_detail_has_sprints_acs_and_latest_run(world):
    status, d, _ = get(world, "/api/projects/BILL")
    assert status == 200
    (sp,) = d["sprints"]
    assert sp["id"] == "S01" and sp["acs"][0]["result"]["state"] == "satisfied"
    assert sp["notes"][-1] == "2026-10-12: chose **bcrypt** (agent: codex)"
    assert d["latest_run"]["result"] == "fail"
    assert d["latest_run"]["missing"][0]["id"] == "HealthTest.healthCheck"
    assert d["status_detail"]["baseline"]["total"] == 5
    assert get(world, "/api/projects/bill")[0] == 200, "keys are case-insensitive"


def test_S05_api_runs_newest_first_with_limit_and_single_run(world):
    status, data, _ = get(world, "/api/projects/BILL/runs?limit=2")
    assert status == 200 and len(data["runs"]) == 2
    a, b = data["runs"]
    assert a["timestamp"] >= b["timestamp"] and a["result"] == "fail"
    status, run, _ = get(world, f"/api/projects/BILL/runs/{a['id']}")
    assert status == 200 and run["id"] == a["id"] and run["failing"][0]["regression"] is True
    status, run, _ = get(world, f"/api/projects/BILL/runs/{b['id']}")
    assert status == 200 and run["id"] == b["id"]
    assert get(world, "/api/projects/BILL/runs?limit=x")[0] == 400
    assert get(world, "/api/projects/BILL/runs/20990101T000000000Z-ffff")[0] == 404
    assert get(world, "/api/projects/BILL/runs/..%2F..%2Fconfig")[0] == 404


def test_S05_api_unknown_project_is_404(world):
    assert get(world, "/api/projects/NOPE")[0] == 404
    assert get(world, "/api/projects/NOPE/runs")[0] == 404
    assert get(world, "/api/nothing")[0] == 404


# --------------------------------------------------------------------------- portfolio status


def test_S05_portfolio_status_and_ordering(world):
    projects = get(world, "/api/projects")[1]["projects"]
    status = {p["key"]: p["status"] for p in projects}
    assert status == {
        "BILL": "fail",
        "WEB": "pass",
        "WEB-2": "none",
        "MOB": "stale",
        "broken": "error",
        "gone": "error",
    }
    order = [p["status"] for p in projects]
    assert order == sorted(order, key=["error", "fail", "stale", "none", "pass"].index), (
        "failing first"
    )
    mob = next(p for p in projects if p["key"] == "MOB")
    assert mob["stale"] == "HEAD moved since the last gate run"
    bad = next(p for p in projects if p["key"] == "broken")
    assert "invalid TOML" in bad["error"]


def test_S05_portfolio_detail_of_a_broken_project_reports_the_error(world):
    status, d, _ = get(world, "/api/projects/broken")
    assert status == 200 and d["status"] == "error"


# --------------------------------------------------------------------------- security


def test_S05_security_rejects_foreign_host_headers(world):
    assert get(world, "/api/projects", host="evil.example")[0] == 403
    assert get(world, "/", host=f"attacker.test:{world['port']}")[0] == 403
    assert get(world, "/api/projects", host=f"localhost:{world['port']}")[0] == 200


def test_S05_security_is_read_only(world):
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert get(world, "/api/projects", method=method)[0] == 405


def test_S05_security_static_files_only_from_the_whitelist(world):
    status, body, res = get(world, "/")
    assert status == 200 and b"<title>sprintwarden</title>" in body
    assert "default-src 'self'" in res.getheader("Content-Security-Policy")
    assert res.getheader("X-Content-Type-Options") == "nosniff"
    assert get(world, "/app.js")[2].getheader("Content-Type").startswith("text/javascript")
    assert get(world, "/style.css")[0] == 200
    for path in (
        "/../pyproject.toml",
        "/static/../server.py",
        "/server.py",
        "/%2e%2e/%2e%2e/etc/passwd",
    ):
        assert get(world, path)[0] == 404, path


def test_S05_security_refuses_non_localhost_bind():
    from sprintwarden.ui.server import make_server
    from sprintwarden.util import SprintError

    with pytest.raises(SprintError):
        make_server("0.0.0.0", 0)


def test_S05_api_no_external_resources_in_static_files():
    from importlib import resources

    static = resources.files("sprintwarden").joinpath("ui", "static")
    for entry in static.iterdir():
        text = entry.read_text(encoding="utf-8")
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", ""), entry.name
        assert "https://" not in text.replace("https?:", ""), (
            f"{entry.name} must not load remote resources"
        )
        assert ".innerHTML" not in text, f"{entry.name}: build DOM with textContent only"


# --------------------------------------------------------------------------- browser smoke test


def _browser():
    pw = pytest.importorskip("playwright.sync_api")
    ctx = pw.sync_playwright().start()
    for kwargs in ({}, {"channel": "chrome"}):
        try:
            return ctx, ctx.chromium.launch(**kwargs)
        except Exception:
            continue
    ctx.stop()
    pytest.skip("no Chromium available for Playwright")


@pytest.mark.browser
@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_S05_browser_five_views_render(world):
    ctx, browser = _browser()
    errors: list[str] = []
    try:
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        base = f"http://127.0.0.1:{world['port']}/"
        # 1. portfolio
        page.goto(base)
        page.wait_for_selector(".card")
        cards = page.locator(".card h3").all_inner_texts()
        assert cards[:2] == ["broken", "gone"] or cards[0] in ("broken", "gone"), cards
        assert page.locator(".card.fail .pill").first.inner_text().startswith("✗")
        # 2. sprint timeline
        page.click("a.card.fail")
        page.wait_for_selector(".sprint")
        assert "S01" in page.locator(".sprint h3").first.inner_text()
        assert page.locator(".notes strong").first.inner_text() == "bcrypt", (
            "minimal markdown renders"
        )
        # 3. regression matrix
        page.click("text=Regression matrix")
        page.wait_for_selector("table.matrix")
        assert page.locator("table.matrix .cell.bad").count() >= 1
        assert "REGRESSION" in (
            page.locator("table.matrix .cell.bad[title]").last.get_attribute("title") or ""
        )
        # 4. trends
        page.click("text=Trends")
        page.wait_for_selector("svg.chart polyline")
        assert page.locator("svg.chart polyline").count() == 2
        # 5. run detail
        page.click("text=Runs")
        page.wait_for_selector("tr.clickable")
        page.locator("tr.clickable").first.click()
        page.wait_for_selector("text=Checks")
        body = page.inner_text("main")
        assert "REGRESSION was passing in baseline" in body and "HealthTest.healthCheck" in body
        assert not errors, errors
    finally:
        browser.close()
        ctx.stop()


def _chrome() -> str | None:
    for candidate in (
        os.environ.get("CHROME_BIN"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome"),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _dump(world, route: str) -> str:
    import subprocess

    chrome = _chrome()
    url = f"http://127.0.0.1:{world['port']}/{route}"
    proc = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--virtual-time-budget=5000",
            "--window-size=1366,900",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.stdout


@pytest.mark.browser
@pytest.mark.skipif(_chrome() is None, reason="needs Chrome/Chromium")
def test_S05_browser_views_render_in_headless_chrome(world):
    """Same five views, rendered by real Chrome running app.js (no Playwright needed)."""
    runs = get(world, "/api/projects/BILL/runs?limit=1")[1]["runs"]
    views = {
        "portfolio": (
            "#/",
            ["Portfolio", "billing", "✗ FAIL", "⏱ STALE", "✓ PASS", "1 regression"],
        ),
        "timeline": ("#/p/BILL/timeline", ["S01 · Auth", "✓ done", "<strong>bcrypt</strong>"]),
        "matrix": ("#/p/BILL/matrix", ["table", 'class="matrix"', "cell bad", "REGRESSION"]),
        "trends": ("#/p/BILL/trends", ["<polyline", "pass rate", "total tests"]),
        # S01 is the current sprint here, so its own broken test "was passing in baseline"
        "run": (
            f"#/p/BILL/run/{runs[0]['id']}",
            [
                "Checks",
                "REGRESSION was passing in baseline",
                "HealthTest.healthCheck",
                "Tests by sprint",
            ],
        ),
    }
    for name, (route, needles) in views.items():
        dom = _dump(world, route)
        for needle in needles:
            assert needle in dom, f"{name}: {needle!r} not rendered"
        assert "Couldn't load" not in dom, name
