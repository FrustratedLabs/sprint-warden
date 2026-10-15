"""Phase S07: the sprint board (per project and across projects) and the refreshed UI."""

from __future__ import annotations

import os
import re
from importlib import resources

import pytest

from sprintwarden.ui.server import serve_in_thread
from tests.helpers import FakeProject, T
from tests.test_s05_dashboard import _chrome, _dump, _mark, get

pytestmark = pytest.mark.slow

STATIC = resources.files("sprintwarden").joinpath("ui", "static")


def _set_acs(p: FakeProject, sid: str, acs: list[tuple[str, str]]) -> None:
    path = next((p.root / ".sprint" / "sprints").glob(f"{sid}-*.md"))
    text = path.read_text(encoding="utf-8")
    start, end = text.index("[[ac]]"), text.index("+++", text.index("[[ac]]"))
    block = "".join(
        f'[[ac]]\nid = "AC{i}"\ndesc = "{d}"\ntests = ["{t}"]\n\n'
        for i, (d, t) in enumerate(acs, 1)
    )
    path.write_text(text[:start] + block + text[end:], encoding="utf-8")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """PLAN: S01 done (now regressed), S02 in progress, S03/S04 planned, S05 parked.
    TWO: one sprint in progress. RAT: ratchet only."""
    home = tmp_path_factory.mktemp("board-home")
    root = tmp_path_factory.mktemp("board-projects")
    old = os.environ.get("SPRINT_HOME")
    os.environ["SPRINT_HOME"] = str(home)

    plan = FakeProject(root / "planner", home)
    base = [T("HealthTest", "healthCheck"), T("AuthTest", "S01_login")]
    assert plan.init("--no-hooks", "--key", "PLAN", "--sprint-title", "Auth", tests=base).code == 0
    _set_acs(plan, "S01", [("Users log in", "S01_login")])
    plan.sprint("gate")
    plan.commit("S01")
    assert plan.sprint("close", "S01").code == 0
    for title, goal in [
        ("Billing", "Invoices total correctly"),
        ("Reports", "Monthly report as PDF"),
        ("Exports", "CSV export"),
        ("Someday", "Nice to have"),
    ]:
        assert plan.sprint("new", title, "--goal", goal).code == 0
    assert plan.sprint("start", "S02").code == 0
    _set_acs(plan, "S02", [("Totals add up", "S02_total"), ("PDF invoice", "S02_pdf")])
    assert plan.sprint("park", "S05", "--reason", "not this quarter").code == 0
    plan.scenario(
        [
            T("HealthTest", "healthCheck"),
            T("AuthTest", "S01_login", "failed", "expected 200 but was 500"),
            T("InvoiceTest", "S02_totalSumsLines"),
        ]
    )
    plan.commit("work")
    plan.sprint("gate", agent="claude-code")

    two = FakeProject(root / "second", home)
    assert (
        two.init(
            "--no-hooks",
            "--key",
            "TWO",
            "--sprint-title",
            "Setup",
            tests=[
                T("BootTest", "S01_boots"),
                T("BootTest", "S01_onArm", "skipped", "no ARM here"),
            ],
        ).code
        == 0
    )
    _set_acs(two, "S01", [("It boots", "S01_boots"), ("It boots on ARM", "S01_onArm")])
    two.commit("setup")
    two.sprint("gate", agent="cursor")

    rat = FakeProject(root / "ratchet", home)
    assert rat.init("--ratchet-only", "--no-hooks", "--key", "RAT").code == 0

    server, _ = serve_in_thread(0)
    yield {"port": server.server_address[1], "home": home}
    server.shutdown()
    server.server_close()
    if old is None:
        os.environ.pop("SPRINT_HOME", None)
    else:
        os.environ["SPRINT_HOME"] = old


@pytest.fixture(autouse=True)
def _keep_world_home(world, monkeypatch):
    monkeypatch.setenv("SPRINT_HOME", str(world["home"]))


# --------------------------------------------------------------------------- API


def test_S07_api_board_every_sprint_has_board_data(world):
    status, d, _ = get(world, "/api/projects/PLAN")
    assert status == 200
    sprints = {s["id"]: s for s in d["sprints"]}
    assert [s["id"] for s in d["sprints"]] == ["S05", "S04", "S03", "S02", "S01"], "newest first"
    assert {k: s["status"] for k, s in sprints.items()} == {
        "S01": "closed",
        "S02": "active",
        "S03": "planned",
        "S04": "planned",
        "S05": "parked",
    }
    s01 = sprints["S01"]
    assert s01["regressed"] is True and s01["failing"] == 1
    assert s01["stats"] == {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    s02 = sprints["S02"]
    assert s02["regressed"] is False, "only done sprints regress"
    assert s02["ac_summary"] == {"total": 2, "satisfied": 1, "failing": 0, "no_tests": 1}
    assert [a["result"]["state"] for a in s02["acs"]] == ["satisfied", "no-tests"]
    assert [k for k, s in sprints.items() if s["next"]] == ["S03"], "lowest planned is up next"
    assert sprints["S05"]["parked_reason"] == "not this quarter" and sprints["S05"]["parked"]
    assert "body" not in s01


def test_S07_api_board_portfolio_summary_has_counts_next_and_roadmap(world):
    projects = {p["key"]: p for p in get(world, "/api/projects")[1]["projects"]}
    plan = projects["PLAN"]
    assert plan["board"] == {"planned": 2, "active": 1, "closed": 1, "parked": 1}
    assert plan["next"] == {"id": "S03", "title": "Reports"}
    assert [(r["id"], r["status"]) for r in plan["roadmap"]] == [
        ("S01", "closed"),
        ("S02", "active"),
        ("S03", "planned"),
        ("S04", "planned"),
        ("S05", "parked"),
    ]
    assert projects["RAT"]["roadmap"] == [] and projects["RAT"]["next"] is None


def test_S07_api_board_endpoint_covers_every_sprints_project(world):
    status, data, _ = get(world, "/api/board")
    assert status == 200 and data["version"]
    assert [p["key"] for p in data["projects"]] == ["PLAN", "TWO"], "sorted by name"
    assert data["without_sprints"] == 1, "the ratchet-only project is counted, not listed"
    two = data["projects"][1]
    assert two["status"] == "pass" and [s["id"] for s in two["sprints"]] == ["S01"]
    assert two["sprints"][0]["ac_summary"]["satisfied"] == 1
    assert get(world, "/api/board", method="POST")[0] == 405


# --------------------------------------------------------------------------- views

needs_chrome = pytest.mark.skipif(_chrome() is None, reason="needs Chrome/Chromium")


def _cards(dom: str, column: str) -> list[str]:
    """Sprint ids of the cards in one board column, in order."""
    m = re.search(rf'<section class="col col-{column}".*?</section>', dom, re.S)
    assert m, f"no {column} column"
    return re.findall(r'data-sprint="(S\d+)"', m.group(0))


@pytest.mark.browser
@needs_chrome
def test_S07_board_columns_show_planned_in_progress_done_and_parked(world):
    dom = _dump(world, "#/p/PLAN/board")
    assert "Couldn't load" not in dom
    assert _cards(dom, "planned") == ["S03", "S04"]
    assert _cards(dom, "active") == ["S02"]
    assert _cards(dom, "closed") == ["S01"]
    assert _cards(dom, "parked") == ["S05"]
    for needle in ("Planned", "In progress", "Done", "Parked", "Up next"):
        assert needle in dom, needle
    assert re.search(
        r'<span class="chip regressed"[^>]*><svg [^>]*data-lucide="x"[^>]*>.*?</svg>regressed</span>',
        dom,
        re.S,
    )
    assert "not this quarter" in dom, "the park reason is on the card"
    for state, lucide, word in (
        ("satisfied", "check", "done"),
        ("no-tests", "circle-dashed", "no tests"),
    ):
        assert re.search(
            rf'<span class="g {state}"><svg [^>]*data-lucide="{lucide}"[^>]*aria-label="{word}"',
            dom,
        ), f"AC state {state}: a Lucide mark that says what it means, not colour alone"
    assert "Read-only: cards move with the" in dom
    assert 'aria-current="page"' in dom and ">Board<" in dom


@pytest.mark.browser
@needs_chrome
def test_S07_board_sprint_panel_shows_acs_notes_and_next_commands(world):
    dom = _dump(world, "#/p/PLAN/board/S02")
    assert 'id="drawer"' in dom and 'role="dialog"' in dom
    assert "Billing" in dom and "Invoices total correctly" in dom
    assert "Acceptance criteria · 1/2" in dom
    assert "sprint close S02" in dom and "sprint park S02" in dom
    assert 'class="bcard active selected' in dom, "the open card is highlighted"
    parked = _dump(world, "#/p/PLAN/board/S05")
    assert "sprint unpark S05" in parked and "not this quarter" in parked
    done = _dump(world, "#/p/PLAN/board/S01")
    assert "Regressed" in done and "1 test failing" in done


@pytest.mark.browser
@needs_chrome
def test_S07_all_projects_board_mixes_projects_with_key_chips(world):
    dom = _dump(world, "#/board")
    assert "Couldn't load" not in dom
    assert _cards(dom, "active") == ["S02", "S01"], "one in-progress sprint per project"
    assert 'data-project="TWO"' in dom and 'data-project="PLAN"' in dom
    assert ">PLAN<" in dom and ">TWO<" in dom, "cards say which project they belong to"
    assert "1 project without sprints not shown" in dom
    assert 'aria-pressed="true"' in dom, "project filters"
    panel = _dump(world, "#/board/TWO/S01")
    assert 'id="drawer"' in panel and "Setup" in panel and "sprint close S01" in panel


# --------------------------------------------------------------------------- design


def _used_icons() -> set[str]:
    js = STATIC.joinpath("app.js").read_text(encoding="utf-8")
    html = STATIC.joinpath("index.html").read_text(encoding="utf-8")
    names = set(re.findall(r'(?:icon|metaItem|fact|add|emptyState)\("([a-z0-9-]+)"', js))
    ternary = r'\? "([a-z0-9-]+)" : "([a-z0-9-]+)"'
    for pair in re.findall(r"(?:icon|metaItem)\([^()]*?" + ternary, js) + re.findall(
        r"function agentIcon.*?" + ternary, js
    ):
        names |= set(pair)
    names |= set(re.findall(r'data-icon="([a-z0-9-]+)"', html))
    for table in re.findall(r"const (?:SPRINT_ICON|MARK) = \{(.*?)\};", js, re.S):
        names |= set(re.findall(r':\s*"([a-z0-9-]+)"', table))
    tabs = re.search(r"const TABS = \[(.*?)\];", js, re.S).group(1)
    names |= set(re.findall(r'\["[a-z]+", "[^"]+", "([a-z0-9-]+)"\]', tabs))
    # the theme and card-size buttons: [value, icon, label]
    names |= set(re.findall(r'\["(?:system|light|dark|full|compact)", "([a-z0-9-]+)", "', js))
    names.add("diamond")  # the milestone marker drawn inside the trends chart
    return names


def test_S07_icons_are_vendored_lucide_with_the_license_shipped(world):
    icons = STATIC.joinpath("icons.js").read_text(encoding="utf-8")
    assert icons.startswith("// Icons from Lucide ") and "ISC License" in icons
    defined = set(re.findall(r'^  "([a-z0-9-]+)": \[', icons, re.M))
    used = _used_icons()
    assert used and used <= defined, f"icons used but not vendored: {sorted(used - defined)}"
    license_text = resources.files("sprintwarden").joinpath("ui", "LICENSE-lucide.txt")
    text = license_text.read_text(encoding="utf-8")
    assert "ISC License" in text and "Feather" in text
    status, body, res = get(world, "/icons.js")
    assert status == 200 and res.getheader("Content-Type").startswith("text/javascript")
    html = STATIC.joinpath("index.html").read_text(encoding="utf-8")
    assert html.index('src="icons.js"') < html.index('src="app.js"')
    assert "Lucide" in html, "credited in the footer"


def test_S07_design_has_light_and_dark_tokens_and_no_inline_styles():
    css = STATIC.joinpath("style.css").read_text(encoding="utf-8")
    root, dark = css.split("@media (prefers-color-scheme: dark)", 1)
    light_tokens = set(re.findall(r"(--[a-z0-9-]+):", root))
    dark_tokens = set(re.findall(r"(--[a-z0-9-]+):", dark.split("\n}\n", 1)[0]))
    fonts = {"--sans", "--serif", "--mono"}
    assert light_tokens - fonts <= dark_tokens, sorted(light_tokens - fonts - dark_tokens)
    for status in ("ok", "bad", "warn", "info", "idle"):
        assert f"--{status}-tint" in dark_tokens
    js = STATIC.joinpath("app.js").read_text(encoding="utf-8")
    assert 'setAttribute("style"' not in js and 'style: "' not in js, (
        "the CSP forbids inline styles"
    )


@pytest.mark.browser
@needs_chrome
def test_S07_design_icons_render_in_every_view(world):
    runs = get(world, "/api/projects/PLAN/runs?limit=1")[1]["runs"]
    for route in (
        "#/",
        "#/board",
        "#/p/PLAN/timeline",
        "#/p/PLAN/board",
        "#/p/PLAN/matrix",
        "#/p/PLAN/trends",
        "#/p/PLAN/runs",
        f"#/p/PLAN/run/{runs[0]['id']}",
    ):
        dom = _dump(world, route)
        assert "Couldn't load" not in dom, route
        assert dom.count('class="icon') >= 4, f"{route}: Lucide icons rendered"
        assert "<path" in dom, route


@pytest.mark.browser
@needs_chrome
def test_S07_board_an_ac_held_back_by_skipped_tests_reads_skipped_not_failing(world):
    two = get(world, "/api/projects/TWO")[1]["sprints"][0]
    assert [a["result"]["state"] for a in two["acs"]] == ["satisfied", "failing"], (
        "the API keeps the spec's rule: a skipped test is not a pass"
    )
    dom = _dump(world, "#/p/TWO/board/S01")
    assert _mark("st st-skipped", "skip-forward", "skipped").search(dom), "the panel says skipped"
    assert re.search(r'<span class="g skipped"><svg [^>]*data-lucide="skip-forward"', dom), (
        "so does the card"
    )
    assert "st-failing" not in dom and 'class="g failing"' not in dom
    assert "Acceptance criteria · 1/2" in dom, "still not done"


def _block(css: str, selector: str) -> str:
    start = css.index(selector)
    return css[start : css.index("\n}\n", start)]


def test_S07_design_theme_can_be_forced_light_or_dark(world):
    css = STATIC.joinpath("style.css").read_text(encoding="utf-8")
    system_dark = _block(css, "@media (prefers-color-scheme: dark)")
    assert ':root:not([data-theme="light"])' in system_dark, "a light choice beats a dark OS"
    forced_dark = _block(css, ':root[data-theme="dark"]')
    tokens = lambda text: dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", text))  # noqa: E731
    assert tokens(forced_dark) == tokens(system_dark), "both dark blocks define the same palette"
    html = STATIC.joinpath("index.html").read_text(encoding="utf-8")
    head = html[: html.index("</head>")]
    assert 'src="theme.js"' in head, "the saved theme applies before first paint"
    assert 'id="theme"' in html
    theme_js = STATIC.joinpath("theme.js").read_text(encoding="utf-8")
    assert "sprintwarden.theme" in theme_js and "dataset.theme" in theme_js
    status, _, res = get(world, "/theme.js")
    assert status == 200 and res.getheader("Content-Type").startswith("text/javascript")
    app = STATIC.joinpath("app.js").read_text(encoding="utf-8")
    for name in ("sun-moon", "sun", "moon"):
        assert f'"{name}"' in app, name


@pytest.mark.browser
@needs_chrome
def test_S07_design_theme_button_renders_with_its_state(world):
    dom = _dump(world, "#/")
    assert 'id="theme"' in dom and 'aria-label="Theme: match system' in dom


# --------------------------------------------------------------------------- icons, card size, trends

GLYPHS = "✓✗✕⏱○●‖∅⊘◆⚠←→■▲▼★☆✔✘"


def test_S07_icons_every_status_mark_is_lucide_not_a_text_glyph():
    for name in ("app.js", "index.html", "style.css"):
        text = STATIC.joinpath(name).read_text(encoding="utf-8")
        found = sorted({ch for ch in text if ch in GLYPHS})
        assert not found, f"{name} draws marks with text glyphs: {found}"
    favicon = STATIC.joinpath("favicon.svg").read_text(encoding="utf-8")
    icons = STATIC.joinpath("icons.js").read_text(encoding="utf-8")
    shield = re.search(r'"shield-check": \[\["path",\{"d":"([^"]+)"', icons).group(1)
    assert shield in favicon, "the favicon is Lucide's shield-check, like the brand mark"


@pytest.mark.browser
@needs_chrome
def test_S07_board_compact_cards_show_only_id_title_and_the_ac_bar(world):
    full = _dump(world, "#/p/PLAN/board")
    assert re.search(
        r'class="seg-btn" aria-pressed="true"[^>]*><svg [^>]*data-lucide="layout-list"', full
    ), "full cards are the default"
    assert "bcard-goal" in full and "bcard-foot" in full
    dom = _dump(world, "?cards=compact#/p/PLAN/board")
    assert 'class="board compact"' in dom
    assert re.search(
        r'class="seg-btn" aria-pressed="true"[^>]*><svg [^>]*data-lucide="rows-3"', dom
    )
    cards = re.findall(r'<a class="bcard [^"]*compact"[^>]*>(.*?)</a>', dom, re.S)
    assert len(cards) == 5, "every sprint is still on the board"
    for card in cards:
        assert 'class="mono bcard-id"' in card and 'class="bcard-title"' in card
        assert 'class="segs' in card, "the AC bar stays"
        for gone in ("bcard-goal", "checklist", "bcard-foot", "bcard-note", "chip"):
            assert gone not in card, gone
    assert _cards(dom, "planned") == ["S03", "S04"] and _cards(dom, "parked") == ["S05"]
    every = _dump(world, "?cards=compact#/board")
    assert 'class="board compact"' in every and ">PLAN<" in every and ">TWO<" in every, (
        "the all-projects board keeps the project key"
    )
    js = STATIC.joinpath("app.js").read_text(encoding="utf-8")
    assert "sprintwarden.board.cards" in js and "localStorage.setItem(CARDS_KEY" in js, "remembered"


@pytest.mark.browser
@needs_chrome
def test_S07_design_trends_explain_what_the_charts_show_in_plain_words(world):
    dom = _dump(world, "#/p/PLAN/trends")
    assert "Couldn't load" not in dom
    text = re.sub(r"<[^>]+>", " ", dom)
    for heading in (
        "Tests now",
        "Pass rate now",
        "Runs that passed",
        "Latest run",
        "What this tells you",
        "Tests in each run",
        "Pass rate",
        "Why it matters",
    ):
        assert heading in text, heading
    assert "records how many tests ran and how many passed" in text, "what the page is"
    for fact in (
        "The latest run failed the gate: 1 failing, 1 regression",
        "That is a regression",
        "Tests grew from 2 to 3 (+1) over these 4 runs",
        "1 of 4 runs failed the gate (25%)",
        "Since the last milestone (close S01",
    ):
        assert fact in text, fact
    charts = re.findall(r'<svg class="chart [^"]*".*?</svg>', dom, re.S)
    assert len(charts) == 2, "one measure per chart"
    assert all(c.count("<polyline") == 1 for c in charts), "never two series on two y-axes"
    assert 'class="ms-label"' in dom and ">close S01<" in dom, "milestones are labelled"
    assert 'data-lucide="x"' in dom and 'class="dot-fail"' in dom, (
        "failed runs are marked by shape too"
    )
    assert re.search(r'class="chart-wrap" tabindex="0" aria-label="[^"]*arrow keys', dom), (
        "keyboard reachable"
    )
    assert 'href="#/p/PLAN/runs"' in dom and "Every run as a table" in dom, (
        "a table view of the same data"
    )
