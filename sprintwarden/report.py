"""Rendering run records for humans (terminal), agents (hooks) and CI (markdown).

Colour is never the only signal: every state also has a ✓/✗ symbol or word.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from sprintwarden.attribution import LEGACY

CHECK_LABELS = {
    "runner": "runner",
    "failures": "failures",
    "missing": "missing",
    "skips": "skips",
    "ratchet": "ratchet",
    "sprint_tests": "tests",
    "acs": "ACs",
}


@dataclass
class Style:
    color: bool = False
    unicode: bool = True

    @classmethod
    def for_stream(cls, stream=None, *, no_color: bool = False) -> Style:
        stream = stream or sys.stdout
        tty = hasattr(stream, "isatty") and stream.isatty()
        color = (
            tty
            and not no_color
            and not os.environ.get("NO_COLOR")
            and os.environ.get("TERM") != "dumb"
        )
        uni = not os.environ.get("SPRINT_ASCII")
        if uni:
            try:
                "✓✗∅←≥–…".encode(getattr(stream, "encoding", None) or "utf-8")
            except (UnicodeEncodeError, LookupError):
                uni = False
        return cls(color=color, unicode=uni)

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def green(self, t: str) -> str:
        return self._c("32", t)

    def red(self, t: str) -> str:
        return self._c("31", t)

    def yellow(self, t: str) -> str:
        return self._c("33", t)

    def dim(self, t: str) -> str:
        return self._c("2", t)

    def bold(self, t: str) -> str:
        return self._c("1", t)

    @property
    def ok(self) -> str:
        return self.green("✓" if self.unicode else "OK")

    @property
    def bad(self) -> str:
        return self.red("✗" if self.unicode else "XX")

    @property
    def warn(self) -> str:
        return self.yellow("!" if self.unicode else "!!")

    @property
    def none(self) -> str:
        return self.dim("–" if self.unicode else "--")

    @property
    def empty(self) -> str:
        return "∅" if self.unicode else "0"

    @property
    def arrow(self) -> str:
        return "←" if self.unicode else "<-"

    def sym(self, ok: bool | None, blocking: bool = True) -> str:
        if ok is None:
            return self.none
        if ok:
            return self.ok
        return self.bad if blocking else self.warn

    def ascii_text(self, text: str) -> str:
        if self.unicode:
            return text
        return text.replace("≥", ">=").replace("–", "-").replace("…", "...").replace("←", "<-")


def ac_symbol(state: str, style: Style) -> str:
    return {"satisfied": style.ok, "failing": style.bad}.get(state, style.empty)


def _sprint_col(sprint: str) -> str:
    return f"{sprint:<7}" if sprint != LEGACY else "legacy "


def _more(n: int, shown: int, style: Style, hint: str = "") -> list[str]:
    if n > shown:
        return [style.dim(f"     … and {n - shown} more{hint}")]
    return []


def render_gate(record: dict[str, Any], style: Style | None = None, *, max_items: int = 50) -> str:
    style = style or Style()
    lines: list[str] = []
    title = f"sprintwarden gate — {record.get('project')}"
    if record.get("sprint"):
        title += f" — {record['sprint']}"
        sprint_title = record.get("sprint_title")
        if sprint_title:
            title += f" ({sprint_title})"
    if record.get("baseline") and record["baseline"].get("ref"):
        title += f" — baseline from {record['baseline']['ref']}"
    lines.append(style.bold(title))
    counts = record.get("counts", {})
    for check in record.get("checks", []):
        cid = check["id"]
        label = CHECK_LABELS.get(cid, cid)
        if cid == "acs":
            acs = "  ".join(
                f"{a['id']} {ac_symbol(a['state'], style)}" for a in record.get("acs", [])
            )
            lines.append(f"  {label:<10} {acs}")
            continue
        sym = style.sym(check["ok"], check["blocking"])
        note = "" if check["blocking"] or check["ok"] else style.dim("  (not blocking)")
        lines.append(f"{sym} {label:<10} {style.ascii_text(check['summary'])}{note}")
        if cid == "runner" and check["ok"] is False and check.get("detail"):
            for d in check["detail"].splitlines()[:40]:
                lines.append(style.dim(f"     {d}"))
        elif cid == "failures":
            items = record.get("failing", [])
            for f in items[:max_items]:
                tag = ""
                if f.get("regression"):
                    tag = style.red(
                        f"  {style.arrow} REGRESSION {f.get('regression_reason', '')}".rstrip()
                    )
                flaky = style.dim(" (flaky)") if f.get("flaky") else ""
                lines.append(f"     {_sprint_col(f['sprint'])}{f['id']}{tag}{flaky}")
                if f.get("message"):
                    lines.append(style.dim(f"             {_short(f['message'], 160)}"))
            lines += _more(counts.get("failing", len(items)), min(len(items), max_items), style)
        elif cid == "missing":
            items = record.get("missing", [])
            for i, m in enumerate(items[:max_items]):
                hint = (
                    style.yellow(
                        f"  {style.arrow} deleted or renamed? use `sprint accept-removal` (human only)"
                    )
                    if i == 0
                    else ""
                )
                lines.append(f"     {_sprint_col(m['sprint'])}{m['id']}{hint}")
            lines += _more(counts.get("missing", len(items)), min(len(items), max_items), style)
        elif cid == "skips":
            items = record.get("new_skips", [])
            for i, m in enumerate(items[:max_items]):
                hint = (
                    style.yellow(f"  {style.arrow} use `sprint allow-skip` (human only)")
                    if i == 0
                    else ""
                )
                was = f" (was {m['was']})" if m.get("was") and m["was"] != "new" else ""
                lines.append(f"     {_sprint_col(m['sprint'])}{m['id']}{was}{hint}")
            lines += _more(counts.get("new_skips", len(items)), min(len(items), max_items), style)
        elif check.get("detail") and check["ok"] is False:
            lines.append(style.dim(f"     {check['detail']}"))
    if record.get("bypassed"):
        lines.append(style.yellow("GATE: BYPASSED"))
    elif record.get("result") == "pass":
        lines.append(style.green(style.bold("GATE: PASS")))
    else:
        lines.append(style.red(style.bold("GATE: FAIL")))
    return "\n".join(lines)


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def environment_problem(record: dict[str, Any]) -> bool:
    """The gate failed only because the test command couldn't start."""
    from sprintwarden.toolchain import is_environment_failure

    runners = record.get("runner") or []
    return (
        bool(runners)
        and any(is_environment_failure(r) for r in runners)
        and not record.get("failing")
    )


def render_agent(record: dict[str, Any], *, max_items: int = 20) -> str:
    """Compact, agent-actionable failure report (for Stop hooks)."""
    lines = [
        f"sprintwarden gate FAILED for {record.get('project')}"
        + (f" (sprint {record['sprint']})" if record.get("sprint") else "")
        + ". You are not done yet."
    ]
    checks = {c["id"]: c for c in record.get("checks", [])}
    runner = checks.get("runner")
    if runner and runner["ok"] is False:
        lines.append(f"\nTEST RUN PROBLEM: {runner['summary']}")
        if runner.get("detail"):
            lines += ["  " + d for d in runner["detail"].splitlines()[:25]]
        if environment_problem(record):
            lines.append(
                "\nThis is an environment problem, not a test failure: the test command could "
                "not start. Don't change tests or .sprint/. Fix the environment if you can "
                "(e.g. create .venv with the test dependencies); otherwise tell the human what is wrong."
            )
    failing = record.get("failing", [])
    regressions = [f for f in failing if f.get("regression")]
    others = [f for f in failing if not f.get("regression")]
    if regressions:
        lines.append("\nREGRESSIONS (tests that used to pass, now failing):")
        for f in regressions[:max_items]:
            lines.append(f"  [{f['sprint']}] {f['id']}: {_short(f.get('message', ''), 200)}")
        if len(regressions) > max_items:
            lines.append(f"  … and {len(regressions) - max_items} more")
    if others:
        lines.append("\nFAILING:")
        for f in others[:max_items]:
            lines.append(f"  [{f['sprint']}] {f['id']}: {_short(f.get('message', ''), 200)}")
        if len(others) > max_items:
            lines.append(f"  … and {len(others) - max_items} more")
    missing = record.get("missing", [])
    if missing:
        lines.append("\nMISSING vs baseline (deleted or renamed?). Restore them:")
        for m in missing[:max_items]:
            lines.append(f"  [{m['sprint']}] {m['id']}")
        if record.get("counts", {}).get("missing", 0) > max_items:
            lines.append(f"  … and {record['counts']['missing'] - max_items} more")
    skips = record.get("new_skips", [])
    if skips:
        lines.append("\nNEWLY SKIPPED (un-skip them):")
        for m in skips[:max_items]:
            lines.append(f"  [{m['sprint']}] {m['id']}")
    for cid in ("ratchet", "sprint_tests"):
        c = checks.get(cid)
        if c and c["ok"] is False and c["blocking"]:
            lines.append(f"\n{CHECK_LABELS.get(cid, cid).upper()}: {c['summary']}")
            if c.get("detail"):
                lines.append(f"  {c['detail']}")
    lines.append(
        "\nFix these; do not delete, skip, rename or weaken tests. If an older test conflicts "
        "with the new requirement, stop and ask the human. Re-check with `sprint gate`."
    )
    return "\n".join(lines)


def render_markdown(record: dict[str, Any], *, max_items: int = 30) -> str:
    """GitHub job summary / PR comment."""
    result = record.get("result", "?")
    icon = {"pass": "✅", "fail": "❌", "bypassed": "⚠️"}.get(result, "❔")
    lines = [f"## {icon} sprintwarden gate: {result.upper()} — {record.get('project')}"]
    meta = []
    if record.get("sprint"):
        meta.append(f"sprint **{record['sprint']}**")
    t = record.get("totals", {})
    if t:
        meta.append(
            f"{t.get('total', 0)} tests ({t.get('failed', 0)} failed, {t.get('skipped', 0)} skipped)"
        )
    if record.get("baseline"):
        b = record["baseline"]
        meta.append(
            f"baseline {b.get('total')} tests" + (f" from `{b['ref']}`" if b.get("ref") else "")
        )
    if meta:
        lines.append(" · ".join(meta))
    lines += ["", "| check | result | details |", "|---|---|---|"]
    for c in record.get("checks", []):
        state = (
            "✅ ok"
            if c["ok"]
            else ("➖ n/a" if c["ok"] is None else ("❌ fail" if c["blocking"] else "⚠️ warn"))
        )
        lines.append(f"| {CHECK_LABELS.get(c['id'], c['id'])} | {state} | {_md(c['summary'])} |")
    failing = record.get("failing", [])
    if failing:
        lines += ["", "### Failing tests", "", "| sprint | test | |", "|---|---|---|"]
        for f in failing[:max_items]:
            tag = f"**REGRESSION** {f.get('regression_reason', '')}" if f.get("regression") else ""
            lines.append(f"| {f['sprint']} | `{_md(f['id'])}` | {tag} |")
        if len(failing) > max_items:
            lines.append(f"| | … and {len(failing) - max_items} more | |")
    for key, title in (("missing", "Missing vs baseline"), ("new_skips", "New skips")):
        items = record.get(key, [])
        if items:
            lines += ["", f"### {title}", ""]
            lines += [f"- `{_md(m['id'])}` ({m['sprint']})" for m in items[:max_items]]
            if len(items) > max_items:
                lines.append(f"- … and {len(items) - max_items} more")
    if record.get("acs"):
        lines += ["", "### Acceptance criteria", ""]
        for a in record["acs"]:
            mark = {"satisfied": "✅", "failing": "❌"}.get(a["state"], "∅")
            lines.append(f"- {mark} **{a['id']}** {_md(a.get('desc', ''))}")
    accepted = record.get("accepted_in_branch")
    if accepted:
        lines += ["", "### ⚠️ Exceptions accepted on this branch (review them)", ""]
        for kind, items in accepted.items():
            for a in items:
                lines.append(
                    f"- {kind}: `{_md(a['id'])}`: {_md(a.get('reason', ''))} (by {a.get('by', '?')})"
                )
    return "\n".join(lines) + "\n"


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")
