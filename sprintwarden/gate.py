"""The gate: run the suite, parse the XML, evaluate every check, record the run.

Checks (all are evaluated and reported; the gate fails if a blocking one fails):

1. ``runner``       XML was found and parsed (and the runner didn't crash).
2. ``failures``     no failing tests in any sprint or the legacy bucket.
3. ``sprint_tests`` the active sprint has tests (``require_current_sprint_tests``).
4. ``acs``          every AC of the active sprint is satisfied (blocks ``close`` only).
5. ``missing``      every baseline test still exists, unless a human accepted its removal.
6. ``skips``        nothing is newly skipped, unless a human allowed it.
7. ``ratchet``      total tests >= baseline total minus accepted removals.

New checks (coverage, lint...) plug in by appending to ``CHECKS``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sprintwarden import __version__, agentdetect, gitutil, runs
from sprintwarden import baseline as bl
from sprintwarden.attribution import (
    LEGACY,
    ACResult,
    Attributor,
    TestIndex,
    evaluate_ac,
    sort_sprint_keys,
    sprint_number,
)
from sprintwarden.config import Config
from sprintwarden.globs import find_files, relpath
from sprintwarden.junit import (
    FAILED,
    PASSED,
    SKIPPED,
    JUnitParseError,
    NotJUnitError,
    ParseResult,
    TestCase,
    merge,
    parse_file,
)
from sprintwarden.runner import RunnerResult, clean_reports, run_all
from sprintwarden.sprintfile import Sprint, load_sprints
from sprintwarden.util import SprintError, iso, plural, read_json, utcnow, write_json

SCHEMA = 1


@dataclass
class Check:
    id: str
    ok: bool | None  # None = not evaluated (e.g. no results to evaluate)
    blocking: bool
    summary: str
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ok": self.ok,
            "blocking": self.blocking,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass
class SuiteResults:
    name: str
    files: list[str] = field(default_factory=list)
    tests: int = 0
    failed: int = 0


@dataclass
class Collected:
    parse: ParseResult
    suites: list[SuiteResults]


@dataclass
class Context:
    cfg: Config
    sprints: list[Sprint]
    current: Sprint | None
    baseline: bl.Baseline | None
    removals: dict[str, bl.Acceptance]
    skips: dict[str, bl.Acceptance]
    collected: Collected
    runner: list[RunnerResult]
    ran: bool
    attributor: Attributor

    @property
    def tests(self) -> dict[str, TestCase]:
        return self.collected.parse.tests

    @property
    def has_results(self) -> bool:
        return bool(self.collected.parse.files)


@dataclass
class Evaluation:
    checks: list[Check]
    failing: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    new_skips: list[dict[str, Any]]
    new_tests: list[str]
    acs: list[ACResult]
    acs_all: list[ACResult]
    by_sprint: dict[str, dict[str, int]]
    totals: dict[str, int]

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks if c.blocking)


@dataclass
class GateResult:
    record: dict[str, Any]
    evaluation: Evaluation
    context: Context
    run_path: Path | None

    @property
    def passed(self) -> bool:
        return self.record["result"] == "pass"


# --------------------------------------------------------------------------- collect


def collect(cfg: Config) -> Collected:
    """Parse the report files of every suite. A file is claimed by the first suite."""
    result = ParseResult()
    suites: list[SuiteResults] = []
    claimed: set[str] = set()
    for suite in cfg.suites:
        sr = SuiteResults(suite.name)
        for path in find_files(cfg.root, suite.reports):
            key = gitutil.path_key(path)
            if key in claimed:
                continue
            claimed.add(key)
            rel = relpath(path, cfg.root)
            try:
                cases = parse_file(path)
            except NotJUnitError as exc:
                result.ignored.append((rel, str(exc)))
                continue
            except JUnitParseError as exc:
                result.errors.append((rel, str(exc)))
                continue
            for c in cases:
                c.file = rel
            sr.files.append(rel)
            sr.tests += len(cases)
            sr.failed += sum(1 for c in cases if c.outcome == FAILED)
            result.files.append(rel)
            merge(result, cases)
        suites.append(sr)
    return Collected(result, suites)


# --------------------------------------------------------------------------- checks


def _sprint_label(t: TestCase) -> str:
    return t.sprint or LEGACY


def check_runner(ctx: Context, ev: Evaluation) -> Check:
    parse = ctx.collected.parse
    problems: list[str] = []
    for r in ctx.runner:
        if r.error:
            problems.append(f"suite {r.suite!r}: {r.error}")
    for sr, r in zip(
        ctx.collected.suites, ctx.runner or [None] * len(ctx.collected.suites), strict=False
    ):
        if not sr.files:
            globs = ", ".join(next(s.reports for s in ctx.cfg.suites if s.name == sr.name))
            problems.append(f"suite {sr.name!r}: no JUnit XML found matching {globs}")
        elif (
            ctx.cfg.fail_on_runner_error
            and r is not None
            and r.exit_code not in (0, None)
            and not r.timed_out
            and sr.failed == 0
        ):
            problems.append(
                f"suite {sr.name!r}: runner exited {r.exit_code} but no test failed "
                "(build error, or a module's tests did not run?)"
            )
    for file, err in parse.errors:
        problems.append(f"unreadable report {file}: {err}")
    duration = sum(r.duration_s for r in ctx.runner)
    files = len(parse.files)
    base = f"{plural(len(parse.tests), 'test')} parsed from {plural(files, 'file')}"
    if ctx.ran:
        base += f" ({duration:.1f}s)"
    else:
        base += " (--no-run: existing reports)"
    if not problems:
        return Check("runner", True, True, base)
    detail_lines = list(problems)
    tails = [
        r for r in ctx.runner if r.tail and (r.exit_code not in (0, None) or r.error or not files)
    ]
    for r in tails:
        detail_lines.append(f"--- last lines of {r.suite!r} output ({r.command}) ---")
        detail_lines.extend(r.tail[-20:])
    if parse.ignored:
        detail_lines.append("ignored non-JUnit XML: " + ", ".join(f for f, _ in parse.ignored[:5]))
    summary = base if files else "no test results"
    if problems:
        summary = f"{summary}; {problems[0]}" if files else problems[0]
    return Check("runner", False, True, summary, "\n".join(detail_lines))


def check_failures(ctx: Context, ev: Evaluation) -> Check:
    if not ctx.has_results:
        return Check("failures", None, True, "not evaluated (no test results)")
    n = len(ev.failing)
    if n == 0:
        return Check("failures", True, True, "no failing tests")
    regressions = sum(1 for f in ev.failing if f["regression"])
    extra = f" ({plural(regressions, 'regression')})" if regressions else ""
    return Check("failures", False, True, f"{n} failing{extra}")


def check_sprint_tests(ctx: Context, ev: Evaluation) -> Check | None:
    if not (ctx.cfg.sprints_mode and ctx.current):
        return None
    sid = ctx.current.id
    count = ev.by_sprint.get(sid, {}).get("total", 0)
    blocking = ctx.cfg.require_current_sprint_tests
    if not ctx.has_results:
        return Check("sprint_tests", None, blocking, "not evaluated (no test results)")
    if count:
        return Check("sprint_tests", True, blocking, f"{plural(count, 'test')} named for {sid}")
    return Check(
        "sprint_tests",
        False,
        blocking,
        f"no tests named for {sid} yet",
        f"name new tests with the sprint id, e.g. {sid}_doesThing / test_{sid}_does_thing",
    )


def check_acs(ctx: Context, ev: Evaluation) -> Check | None:
    if not (ctx.cfg.sprints_mode and ctx.current and ctx.current.acs):
        return None
    ok = all(a.satisfied for a in ev.acs)
    done = sum(1 for a in ev.acs if a.satisfied)
    summary = f"{done}/{len(ev.acs)} acceptance criteria satisfied"
    return Check("acs", ok, False, summary)


def check_missing(ctx: Context, ev: Evaluation) -> Check:
    blocking = ctx.cfg.fail_on_missing_tests
    if ctx.baseline is None:
        return Check("missing", True, blocking, "no baseline yet")
    if not ctx.has_results:
        return Check("missing", None, blocking, "not evaluated (no test results)")
    n = len(ev.missing)
    if n == 0:
        return Check("missing", True, blocking, "no tests missing vs baseline")
    return Check("missing", False, blocking, f"{plural(n, 'test')} missing vs baseline")


def check_skips(ctx: Context, ev: Evaluation) -> Check:
    blocking = ctx.cfg.fail_on_new_skips
    if ctx.baseline is None:
        return Check("skips", True, blocking, "no baseline yet")
    if not ctx.has_results:
        return Check("skips", None, blocking, "not evaluated (no test results)")
    n = len(ev.new_skips)
    if n == 0:
        return Check("skips", True, blocking, "no new skips")
    return Check("skips", False, blocking, f"{plural(n, 'new skip')}")


def check_ratchet(ctx: Context, ev: Evaluation) -> Check:
    if ctx.baseline is None:
        return Check("ratchet", True, True, "no baseline yet (run `sprint baseline`)")
    if not ctx.has_results:
        return Check("ratchet", None, True, "not evaluated (no test results)")
    accepted = sum(1 for t in ctx.removals if t in ctx.baseline.tests)
    required = ctx.baseline.total - accepted
    total = ev.totals["total"]
    new = len(ev.new_tests)
    tail = f" (+{new} new)" if new else ""
    accepted_note = f" ({ctx.baseline.total} - {accepted} accepted removals)" if accepted else ""
    if total >= required:
        return Check("ratchet", True, True, f"{total} ≥ {required}{accepted_note}{tail}")
    return Check(
        "ratchet",
        False,
        True,
        f"{total} < {required}{accepted_note}: the suite shrank",
        "tests only go up; restore the tests or have a human run `sprint accept-removal`",
    )


CheckFn = Callable[[Context, Evaluation], "Check | None"]
CHECKS: list[CheckFn] = [
    check_runner,
    check_failures,
    check_missing,
    check_skips,
    check_ratchet,
    check_sprint_tests,
    check_acs,
]


# --------------------------------------------------------------------------- evaluate


def evaluate(ctx: Context) -> Evaluation:
    tests = ctx.tests
    for t in tests.values():
        t.sprint = ctx.attributor.sprint_of(t.classname, t.name)

    totals = {"total": len(tests), "passed": 0, "failed": 0, "skipped": 0}
    by_sprint: dict[str, dict[str, int]] = {}
    for t in tests.values():
        totals[t.outcome] += 1
        bucket = by_sprint.setdefault(
            t.sprint, {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
        )
        bucket["total"] += 1
        bucket[t.outcome] += 1
    by_sprint = {k: by_sprint[k] for k in sort_sprint_keys(by_sprint)}

    base = ctx.baseline
    closed = {s.id for s in ctx.sprints if s.status == "closed"}
    current_num = sprint_number(ctx.current.id) if ctx.current else None

    def regression(t: TestCase) -> tuple[bool, str]:
        if base and base.tests.get(t.id) == PASSED:
            own = t.sprint == LEGACY or (ctx.current is not None and t.sprint == ctx.current.id)
            return True, "was passing in baseline" if own else f"from sprint {t.sprint}"
        if ctx.cfg.sprints_mode and t.sprint != LEGACY:
            if t.sprint in closed:
                return True, f"from sprint {t.sprint}"
            if current_num is not None and sprint_number(t.sprint) < current_num:
                return True, f"from sprint {t.sprint}"
        return False, ""

    failing = []
    for t in tests.values():
        if t.outcome != FAILED:
            continue
        is_reg, why = regression(t)
        entry = {"id": t.id, "sprint": t.sprint, "regression": is_reg, "message": t.message}
        if why:
            entry["regression_reason"] = why
        if t.flaky:
            entry["flaky"] = True
        if t.file:
            entry["file"] = t.file
        failing.append(entry)
    failing.sort(key=lambda f: (not f["regression"], sprint_number(f["sprint"]), f["id"]))

    missing: list[dict[str, Any]] = []
    new_skips: list[dict[str, Any]] = []
    new_tests: list[str] = []
    if base is not None and ctx.has_results:
        for test_id, outcome in base.tests.items():
            if test_id not in tests and test_id not in ctx.removals:
                sprint = _attr_id(ctx.attributor, test_id)
                missing.append({"id": test_id, "sprint": sprint, "baseline_outcome": outcome})
        missing.sort(key=lambda m: (sprint_number(m["sprint"]), m["id"]))
        for t in tests.values():
            if t.id not in base.tests:
                new_tests.append(t.id)
            if t.outcome == SKIPPED and base.tests.get(t.id) != SKIPPED and t.id not in ctx.skips:
                entry = {"id": t.id, "sprint": t.sprint, "message": t.message}
                entry["was"] = base.tests.get(t.id, "new")
                new_skips.append(entry)
        new_skips.sort(key=lambda m: (sprint_number(m["sprint"]), m["id"]))

    outcomes = {t.id: t.outcome for t in tests.values()}
    index = TestIndex(outcomes)
    acs_all: list[ACResult] = []
    for s in ctx.sprints:
        for ac in s.acs:
            acs_all.append(evaluate_ac(s.id, ac.id, ac.desc, ac.tests, outcomes, index))
    acs = [a for a in acs_all if ctx.current and a.sprint == ctx.current.id]

    ev = Evaluation(
        checks=[],
        failing=failing,
        missing=missing,
        new_skips=new_skips,
        new_tests=new_tests,
        acs=acs,
        acs_all=acs_all,
        by_sprint=by_sprint,
        totals=totals,
    )
    for fn in CHECKS:
        check = fn(ctx, ev)
        if check is not None:
            ev.checks.append(check)
    return ev


def _attr_id(attributor: Attributor, test_id: str) -> str:
    """Attribute a bare test id (from the baseline): split at the last dot, so the
    name part wins like it does for parsed tests."""
    classname, _, name = test_id.rpartition(".")
    return attributor.sprint_of(classname, name)


# --------------------------------------------------------------------------- run


def load_context_parts(cfg: Config, baseline_ref: str | None = None):
    sprints: list[Sprint] = []
    current: Sprint | None = None
    if cfg.sprints_mode:
        sprints, _ = load_sprints(cfg.paths.sprints)
        if cfg.sprint_current:
            current = next((s for s in sprints if s.id == cfg.sprint_current), None)
    baseline = None
    if baseline_ref:
        baseline = bl.load_baseline_from_ref(cfg.paths, baseline_ref)
    if baseline is None:
        baseline = bl.load_baseline(cfg.paths)
    removals = bl.effective(bl.load_removals(cfg.paths), baseline)
    skips = bl.effective(bl.load_skips(cfg.paths), baseline)
    return sprints, current, baseline, removals, skips


@contextlib.contextmanager
def gate_lock(cfg: Config, *, wait_s: float | None = None) -> Iterator[None]:
    """One gate run per working tree at a time (parallel agents share reports)."""
    lock = cfg.paths.lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    max_age = sum(s.timeout_minutes for s in cfg.suites) * 60 + 600
    deadline = time.monotonic() + (wait_s if wait_s is not None else max_age)
    announced = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as fh:
                json.dump({"pid": os.getpid(), "started": iso()}, fh)
            break
        except FileExistsError:
            if _lock_is_stale(lock, max_age):
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if time.monotonic() > deadline:
                raise SprintError(
                    f"another gate run holds {lock}", hint="delete it if no gate is running"
                ) from None
            if not announced:
                print("sprintwarden: waiting for another gate run in this tree…", file=sys.stderr)
                announced = True
            time.sleep(0.5)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _lock_is_stale(lock: Path, max_age: float) -> bool:
    try:
        age = time.time() - lock.stat().st_mtime
        data = json.loads(lock.read_text() or "{}")
    except (OSError, ValueError):
        return True
    if age > max_age:
        return True
    pid = data.get("pid")
    if isinstance(pid, int) and os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
    return False


def run_gate(
    cfg: Config,
    *,
    run: bool = True,
    verbose: bool = False,
    trigger: str = "cli",
    baseline_ref: str | None = None,
    collect_dir: Path | None = None,
    write: bool = True,
    agent: str | None = None,
) -> GateResult:
    started = utcnow()
    t0 = time.monotonic()
    sprints, current, baseline, removals, skips = load_context_parts(cfg, baseline_ref)
    with gate_lock(cfg):
        runner_results: list[RunnerResult] = []
        if run:
            if cfg.clean_reports_before_run:
                clean_reports(cfg)
            runner_results = run_all(cfg, verbose=verbose)
        collected = collect(cfg)
        if collect_dir is not None:
            _copy_reports(cfg, collected.parse.files, collect_dir)
        ctx = Context(
            cfg=cfg,
            sprints=sprints,
            current=current,
            baseline=baseline,
            removals=removals,
            skips=skips,
            collected=collected,
            runner=runner_results,
            ran=run,
            attributor=Attributor(cfg.id_pattern),
        )
        ev = evaluate(ctx)
        record = build_record(
            ctx,
            ev,
            started=started,
            duration=time.monotonic() - t0,
            trigger=trigger,
            agent=agent or agentdetect.detect(),
            baseline_ref=baseline_ref,
        )
        run_path = None
        if write:
            run_path = save(cfg, record, ev, ctx)
    return GateResult(record=record, evaluation=ev, context=ctx, run_path=run_path)


def build_record(
    ctx: Context,
    ev: Evaluation,
    *,
    started,
    duration: float,
    trigger: str,
    agent: str,
    baseline_ref: str | None,
) -> dict[str, Any]:
    cfg = ctx.cfg
    git = gitutil.info(cfg.root)
    base = ctx.baseline
    return {
        "schema": SCHEMA,
        "id": runs.new_run_id(),
        "project": cfg.name,
        "key": cfg.key,
        "mode": cfg.mode,
        "sprint": ctx.current.id if ctx.current else None,
        "sprint_title": ctx.current.title if ctx.current else None,
        "timestamp": iso(started),
        "git": git,
        "agent": agent,
        "trigger": trigger,
        "bypassed": False,
        "ran": ctx.ran,
        "duration_s": round(duration, 2),
        "result": "pass" if ev.passed else "fail",
        "checks": [c.to_json() for c in ev.checks],
        "totals": ev.totals,
        "by_sprint": ev.by_sprint,
        "acs": [a.to_json(test_cap=50) for a in ev.acs],
        "failing": ev.failing,
        "new_skips": ev.new_skips,
        "missing": ev.missing,
        "new_tests": ev.new_tests,
        "counts": {
            "failing": len(ev.failing),
            "regressions": sum(1 for f in ev.failing if f["regression"]),
            "missing": len(ev.missing),
            "new_skips": len(ev.new_skips),
            "new_tests": len(ev.new_tests),
            "flaky": sum(1 for t in ctx.tests.values() if t.flaky),
        },
        "baseline": (base.summary() | ({"ref": baseline_ref} if baseline_ref else {}))
        if base
        else None,
        "runner": [r.to_json() for r in ctx.runner],
        "reports": len(ctx.collected.parse.files),
        "version": __version__,
    }


def save(cfg: Config, record: dict[str, Any], ev: Evaluation, ctx: Context) -> Path:
    path = runs.write_run(
        cfg.paths,
        record,
        latest_extra={"acs_all": [a.to_json(test_cap=50) for a in ev.acs_all]},
    )
    write_json(
        cfg.paths.latest_full,
        {
            "id": record["id"],
            "fingerprint": record["git"].get("fingerprint"),
            "head": record["git"].get("head"),
            "result": record["result"],
            "tests": {t.id: t.outcome for t in ctx.tests.values()},
            "failing": ev.failing,
            "missing": ev.missing,
            "new_skips": ev.new_skips,
        },
    )
    if cfg.history_keep:
        runs.prune(cfg.paths, cfg.history_keep)
    return path


def load_full(cfg: Config) -> dict[str, Any] | None:
    try:
        data = read_json(cfg.paths.latest_full)
    except SprintError:
        return None
    return data if isinstance(data, dict) else None


def record_bypass(cfg: Config, *, trigger: str, reason: str = "SPRINT_SKIP=1") -> Path:
    """Record that a hook was bypassed. Doesn't touch latest.json: no gate ran."""
    git = gitutil.info(cfg.root)
    record = {
        "schema": SCHEMA,
        "id": runs.new_run_id(),
        "project": cfg.name,
        "key": cfg.key,
        "mode": cfg.mode,
        "sprint": cfg.sprint_current or None,
        "timestamp": iso(),
        "git": git,
        "agent": agentdetect.detect(),
        "trigger": trigger,
        "bypassed": True,
        "bypass_reason": reason,
        "ran": False,
        "duration_s": 0,
        "result": "bypassed",
        "checks": [],
        "totals": {},
        "by_sprint": {},
        "acs": [],
        "failing": [],
        "new_skips": [],
        "missing": [],
        "version": __version__,
    }
    path = runs.run_file(cfg.paths, record["id"])
    write_json(path, record)
    return path


def _copy_reports(cfg: Config, files: list[str], dest: Path) -> None:
    dest = dest if dest.is_absolute() else cfg.root / dest
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            shutil.copy2(cfg.root / rel, target)
