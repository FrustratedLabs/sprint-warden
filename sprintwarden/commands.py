"""Command implementations. Each returns an :class:`Outcome`; ``cli.py`` prints
it as text or JSON and turns ``code`` into the exit status (0 ok, 1 gate
failure, 2 config/usage error)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sprintwarden import __version__, agentdetect, gitutil, project, registry, runs
from sprintwarden import baseline as bl
from sprintwarden.attribution import TestMatcher, sort_sprint_keys
from sprintwarden.config import SPRINT_DIR, Config, Paths, find_root, load_config, require_root
from sprintwarden.gate import GateResult, load_full, run_gate
from sprintwarden.report import Style, ac_symbol, render_gate, render_markdown
from sprintwarden.sprintfile import load_sprints, validate_sprints
from sprintwarden.stacks import Stack, detect_stacks, get_stack, load_stacks
from sprintwarden.util import (
    EXIT_GATE_FAIL,
    EXIT_OK,
    EXIT_USAGE,
    SprintError,
    plural,
    read_text,
)

RATCHET_CHECKS = ("runner", "failures", "missing", "skips", "ratchet")


@dataclass
class Outcome:
    code: int = EXIT_OK
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass
class Env:
    cwd: Path
    json: bool = False
    style: Style = field(default_factory=Style)
    interactive: bool = False

    def root(self) -> Path:
        return require_root(self.cwd)

    def config(self) -> Config:
        return load_config(self.root())


class HumanOnlyError(SprintError):
    pass


def guard_human(command: str, args: Any) -> str:
    """Refuse human-only commands in an agent environment. Returns the 'by' label."""
    agent = agentdetect.detect()
    if agentdetect.is_agent(agent) and not getattr(args, "i_am_human", False):
        raise HumanOnlyError(
            f"`sprint {command}` is human-only and this looks like an agent session ({agent}).",
            hint=(
                "If you are an AI agent: stop and ask the human to run it. "
                "If you are a human in an agent's terminal, add --i-am-human. "
                "(This is a speed bump, not security; CI and code review are the real check.)"
            ),
        )
    who = _git_user()
    if agentdetect.is_agent(agent):
        return f"{who} (--i-am-human, in {agent})"
    return who


def _git_user() -> str:
    proc = gitutil.git(Path.cwd(), "config", "user.name")
    name = proc.stdout.strip() if proc.returncode == 0 else ""
    return name or os.environ.get("USER") or os.environ.get("USERNAME") or "human"


# --------------------------------------------------------------------------- init


def _choose_stack(env: Env, root: Path, args: Any) -> tuple[Stack, str, list[str]]:
    if args.stack:
        stack = get_stack(args.stack)
    else:
        found = detect_stacks(root)
        stack = found[0] if found else get_stack("custom")
        if env.interactive and not args.yes:
            names = ", ".join(s.name for s in found) or "none"
            print(f"Detected stacks: {names}", file=sys.stderr)
            prompt = f"Use stack [{stack.name}]? (Enter to accept, or type one of {', '.join(sorted(load_stacks()))}): "
            answer = input(prompt).strip()
            if answer:
                stack = get_stack(answer)
        elif len(found) > 1:
            print(
                f"sprintwarden: several stacks detected ({', '.join(s.name for s in found)}); "
                f"using {stack.name}. Pass --stack to choose, or add [[test.suites]] for a monorepo.",
                file=sys.stderr,
            )
    command = args.command or stack.command
    reports = args.reports or stack.reports
    if not command or not reports:
        if env.interactive and not args.yes:
            command = command or input("Test command (must write JUnit XML): ").strip()
            raw = input("JUnit XML report glob(s), comma separated: ").strip()
            reports = reports or [r.strip() for r in raw.split(",") if r.strip()]
        if not command or not reports:
            raise SprintError(
                "no test stack detected",
                hint="pass --stack <name> (" + ", ".join(sorted(load_stacks())) + ") "
                "or --command '<cmd>' --reports '<glob>'",
            )
    return stack, command, reports


def cmd_init(env: Env, args: Any) -> Outcome:
    root = env.cwd.resolve()
    paths = Paths(root)
    lines: list[str] = []
    changes = project.Changes()
    top = gitutil.toplevel(root)
    if top is not None and top.resolve() != root:
        changes.warnings.append(
            f"initializing in a subdirectory of the git repo {top}; "
            "that's fine for a monorepo package, otherwise run init at the repo root"
        )
    existing = paths.config.is_file()
    mode = "ratchet-only" if args.ratchet_only else "sprints"
    stack: Stack | None = None
    if existing and not args.force:
        cfg = load_config(root)
        changes.skipped.append(
            f".sprint/config.toml exists (mode {cfg.mode}); use --force to rewrite it"
        )
        if args.ratchet_only and cfg.mode != "ratchet-only":
            changes.warnings.append(
                "project is in sprints mode; --ratchet-only ignored (edit project.mode)"
            )
        stack = load_stacks().get(cfg.stack)
    else:
        stack, command, reports = _choose_stack(env, root, args)
        name = args.name or root.name
        key = args.key or re.sub(r"[^A-Za-z0-9]", "", name).upper()[:4] or "PROJ"
        text = project.render_config(
            name=name,
            key=key,
            mode=mode,
            stack=stack,
            command=command,
            reports=reports,
            current="S01" if mode == "sprints" else "",
        )
        paths.dir.mkdir(parents=True, exist_ok=True)
        paths.config.write_text(text, encoding="utf-8", newline="\n")
        changes.done.append(
            f"{'rewrote' if existing else 'created'} .sprint/config.toml (stack {stack.name}: {command})"
        )
        cfg = load_config(root)

    example = stack.example_test if stack else "S01_doesThing"
    changes.merge(project.write_sprint_skeleton(paths))
    if cfg.sprints_mode:
        changes.merge(
            project.write_first_sprint(paths, args.sprint_title or "First sprint", example)
        )
    changes.merge(project.write_agents_md(cfg, example, refresh=args.force))
    changes.merge(project.write_claude_md(root))
    if args.with_guard and not cfg.claude_pretool_guard:
        from sprintwarden.config import set_value

        set_value(root, "hooks", "claude_pretool_guard", True)
        cfg = load_config(root)
    if not args.no_hooks:
        if cfg.claude_stop_hook or cfg.claude_session_start or cfg.claude_pretool_guard:
            changes.merge(
                project.merge_claude_settings(
                    root,
                    stop=cfg.claude_stop_hook,
                    session=cfg.claude_session_start,
                    pretool=cfg.claude_pretool_guard,
                )
            )
        if cfg.git_pre_push:
            changes.merge(project.install_pre_push(root))
        for agent in _split_agents(args.agents):
            from sprintwarden.hooks import install as agent_install

            changes.merge(agent_install.install(root, agent))
    changes.merge(project.update_gitignore(root, history_in_git=cfg.history_in_git))
    changes.merge(project.update_gitattributes(root))
    changes.merge(project.register_project(root))

    st = env.style
    lines.append(st.bold(f"sprintwarden init — {cfg.name} ({cfg.mode})"))
    lines += [f"{st.ok} {d}" for d in changes.done]
    lines += [st.dim(f"  · {s}") for s in changes.skipped]
    lines += [f"{st.warn} {w}" for w in changes.warnings]

    data: dict[str, Any] = {
        "root": str(root),
        "mode": cfg.mode,
        "stack": cfg.stack,
        "done": changes.done,
        "skipped": changes.skipped,
        "warnings": changes.warnings,
        "baseline": None,
    }
    code = EXIT_OK
    if args.no_gate:
        lines.append(
            st.dim("  · skipped the first gate run (--no-gate); run `sprint baseline` when ready")
        )
    elif bl.load_baseline(paths) is not None:
        lines.append(st.dim("  · baseline already exists"))
    else:
        lines.append(f"\nRunning the first gate: {' && '.join(s.command for s in cfg.suites)}")
        result = run_gate(cfg, trigger="init")
        data["gate"] = result.record
        lines.append(render_gate(result.record, st))
        if _ratchet_ok(result):
            base = _write_baseline_from(cfg, result, reason="init")
            data["baseline"] = base.summary()
            lines.append(
                f"{st.ok} baseline written: {plural(base.total, 'test')} must keep existing and passing"
            )
        else:
            code = EXIT_GATE_FAIL
            lines.append(_baseline_refusal_hint(result, st))
    lines.append("")
    lines.append(_next_steps(cfg))
    return Outcome(code, data, "\n".join(lines))


def _split_agents(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [a.strip().lower() for a in raw.split(",") if a.strip()]


def _next_steps(cfg: Config) -> str:
    if cfg.sprints_mode:
        return (
            "Next: edit .sprint/sprints/S01-*.md (goal + acceptance criteria), name tests S01_…, "
            "run `sprint gate`, and commit .sprint/ plus the agent files (AGENTS.md, CLAUDE.md, .claude/)."
        )
    return (
        "Next: commit .sprint/ plus the agent files (AGENTS.md, CLAUDE.md, .claude/). From now on "
        "`sprint gate` fails if a test that exists today is deleted, skipped or broken."
    )


def _ratchet_ok(result: GateResult) -> bool:
    return all(c.ok for c in result.evaluation.checks if c.id in RATCHET_CHECKS and c.blocking)


def _baseline_refusal_hint(result: GateResult, st: Style) -> str:
    ids = [c.id for c in result.evaluation.checks if c.id in RATCHET_CHECKS and not c.ok]
    if "runner" in ids:
        return st.yellow(
            "Baseline NOT written: the test command produced no usable JUnit XML. Fix [test] "
            "command/reports in .sprint/config.toml (see `sprint doctor`), then run `sprint baseline`."
        )
    if "failures" in ids:
        return st.yellow(
            "Baseline NOT written: some tests fail today. Fix them, or mark known failures as "
            "skipped in code (they are recorded as skipped), then run `sprint baseline`."
        )
    return st.yellow("Baseline NOT written; fix the checks above, then run `sprint baseline`.")


def _write_baseline_from(cfg: Config, result: GateResult, *, reason: str) -> bl.Baseline:
    tests = {t.id: t.outcome for t in result.context.tests.values()}
    record = result.record
    base = bl.write_baseline(
        cfg.paths,
        tests,
        reason=reason,
        sprint=record.get("sprint"),
        git=record.get("git") or {},
        run=record.get("id"),
    )
    runs.mark_milestone(cfg.paths, record["id"], reason)
    return base


# --------------------------------------------------------------------------- gate


def cmd_gate(env: Env, args: Any) -> Outcome:
    if args.hook:
        from sprintwarden.hooks.claude_stop import run_hook

        return Outcome(run_hook(env.cwd), {}, "")
    cfg = env.config()
    result = run_gate(
        cfg,
        run=not args.no_run,
        verbose=args.verbose,
        trigger=args.trigger or ("ci" if agentdetect.detect() == agentdetect.CI else "cli"),
        baseline_ref=args.baseline_ref,
        collect_dir=Path(args.collect_reports) if args.collect_reports else None,
    )
    record = result.record
    if args.baseline_ref:
        record["accepted_in_branch"] = accepted_in_branch(cfg, args.baseline_ref)
    code = EXIT_OK if result.passed else EXIT_GATE_FAIL
    if args.format == "markdown":
        return Outcome(code, record, render_markdown(record))
    return Outcome(code, record, render_gate(record, env.style))


def accepted_in_branch(cfg: Config, ref: str) -> dict[str, list[dict]]:
    """Removals/skips present here but not at ``ref``: what this branch asks reviewers to accept."""
    import json

    out: dict[str, list[dict]] = {}
    for kind, path, key in (
        ("removal", cfg.paths.removals, "removals"),
        ("skip", cfg.paths.skips, "skips"),
    ):
        rel = path.relative_to(cfg.root).as_posix()
        base_text = gitutil.show_file(cfg.root, ref, rel)
        try:
            base_ids = {a["id"] for a in json.loads(base_text).get(key, [])} if base_text else set()
        except (ValueError, AttributeError, TypeError):
            base_ids = set()
        here = bl.load_removals(cfg.paths) if kind == "removal" else bl.load_skips(cfg.paths)
        added = [a.to_json() for a in here if a.id not in base_ids]
        if added:
            out[kind] = added
    return out


# --------------------------------------------------------------------------- baseline


def _fresh_gate(env: Env, cfg: Config, args: Any, trigger: str) -> GateResult:
    clean = gitutil.is_dirty(cfg.root)
    if clean is True:
        raise SprintError(
            "the working tree has uncommitted changes",
            hint="commit or stash them first: the baseline must describe a commit (clean HEAD)",
        )
    return run_gate(cfg, run=not getattr(args, "no_run", False), trigger=trigger)


def cmd_baseline(env: Env, args: Any) -> Outcome:
    guard_human("baseline", args)
    cfg = env.config()
    old = bl.load_baseline(cfg.paths)
    result = _fresh_gate(env, cfg, args, "baseline")
    st = env.style
    if not _ratchet_ok(result):
        text = render_gate(result.record, st) + "\n" + _baseline_refusal_hint(result, st)
        return Outcome(EXIT_GATE_FAIL, {"gate": result.record, "baseline": None}, text)
    reason = "baseline" + (f": {args.reason}" if args.reason else "")
    new = _write_baseline_from(cfg, result, reason=reason)
    added = len(set(new.tests) - set(old.tests)) if old else new.total
    removed = len(set(old.tests) - set(new.tests)) if old else 0
    text = (
        render_gate(result.record, st)
        + f"\n{st.ok} baseline: {plural(new.total, 'test')}"
        + (f" (was {old.total}: +{added}, -{removed})" if old else "")
        + "\nCommit .sprint/baseline.json."
    )
    return Outcome(
        EXIT_OK,
        {"gate": result.record, "baseline": new.summary(), "added": added, "removed": removed},
        text,
    )


# --------------------------------------------------------------------------- accept-removal / allow-skip


def _expand(specs: list[str], universe: list[str]) -> tuple[list[str], list[str]]:
    """Expand ``/regex/`` specs against known test ids. Returns (ids, unmatched specs)."""
    ids: list[str] = []
    unmatched: list[str] = []
    for spec in specs:
        if spec.startswith("/") and spec.endswith("/") and len(spec) > 2:
            m = TestMatcher(spec)
            hits = [t for t in universe if m.matches(t)]
            if not hits:
                unmatched.append(spec)
            ids += [h for h in hits if h not in ids]
        elif spec not in ids:
            ids.append(spec)
            if universe and spec not in universe:
                unmatched.append(spec)
    return ids, unmatched


def _require_reason(args: Any) -> str:
    reason = (args.reason or "").strip()
    if len(reason) < 3:
        raise SprintError(
            "a --reason is required (it is recorded next to the exception for reviewers)"
        )
    return reason


def cmd_accept_removal(env: Env, args: Any) -> Outcome:
    by = guard_human("accept-removal", args)
    reason = _require_reason(args)
    cfg = env.config()
    base = bl.load_baseline(cfg.paths)
    if base is None:
        raise SprintError("there is no baseline yet, so nothing can be missing")
    specs = list(args.tests or [])
    if args.all_missing:
        full = load_full(cfg)
        if not full:
            raise SprintError("no gate results yet", hint="run `sprint gate` first")
        specs += [m["id"] for m in full.get("missing", [])]
    if not specs:
        raise SprintError("name the test ids to accept, or pass --all-missing")
    ids, unmatched = _expand(specs, sorted(base.tests))
    items = bl.load_removals(cfg.paths)
    bl.add(items, ids, reason=reason, by=by, git_head=gitutil.head(cfg.root))
    bl.save_removals(cfg.paths, items)
    st = env.style
    lines = [f"{st.ok} accepted {plural(len(ids), 'removal')} ({reason})"]
    lines += [f"     {i}" for i in ids[:50]]
    if len(ids) > 50:
        lines.append(f"     … and {len(ids) - 50} more")
    for u in unmatched:
        lines.append(f"{st.warn} {u} is not in the baseline (recorded anyway)")
    lines.append(
        "Commit .sprint/removals.json. The next `sprint baseline` / `sprint close` drops these tests."
    )
    return Outcome(
        EXIT_OK,
        {"accepted": ids, "unmatched": unmatched, "reason": reason, "by": by},
        "\n".join(lines),
    )


def cmd_allow_skip(env: Env, args: Any) -> Outcome:
    by = guard_human("allow-skip", args)
    reason = _require_reason(args)
    cfg = env.config()
    full = load_full(cfg) or {}
    specs = list(args.tests or [])
    if args.all_new:
        if not full:
            raise SprintError("no gate results yet", hint="run `sprint gate` first")
        specs += [m["id"] for m in full.get("new_skips", [])]
    if not specs:
        raise SprintError("name the test ids to allow, or pass --all-new")
    ids, unmatched = _expand(specs, sorted((full.get("tests") or {}).keys()))
    items = bl.load_skips(cfg.paths)
    permanent = bool(getattr(args, "permanent", False))
    bl.add(items, ids, reason=reason, by=by, git_head=gitutil.head(cfg.root), permanent=permanent)
    bl.save_skips(cfg.paths, items)
    st = env.style
    kind = "permanent skip" if permanent else "skip"
    lines = [f"{st.ok} allowed {plural(len(ids), kind)} ({reason})"] + [
        f"     {i}" for i in ids[:50]
    ]
    if permanent:
        lines.append(st.dim("  stays allowed across future baselines (environment-dependent test)"))
    for u in unmatched:
        lines.append(f"{st.warn} {u} was not in the latest run (recorded anyway)")
    lines.append("Commit .sprint/skips.json.")
    return Outcome(
        EXIT_OK,
        {
            "allowed": ids,
            "unmatched": unmatched,
            "reason": reason,
            "by": by,
            "permanent": permanent,
        },
        "\n".join(lines),
    )


# --------------------------------------------------------------------------- history


def run_summary(r: dict[str, Any]) -> dict[str, Any]:
    t = r.get("totals") or {}
    c = r.get("counts") or {}
    return {
        "id": r.get("id"),
        "timestamp": r.get("timestamp"),
        "result": r.get("result"),
        "sprint": r.get("sprint"),
        "total": t.get("total"),
        "failed": t.get("failed"),
        "skipped": t.get("skipped"),
        "regressions": c.get("regressions", 0),
        "missing": c.get("missing", 0),
        "new_skips": c.get("new_skips", 0),
        "agent": r.get("agent"),
        "trigger": r.get("trigger"),
        "head": ((r.get("git") or {}).get("head") or "")[:10] or None,
        "duration_s": r.get("duration_s"),
        "bypassed": r.get("bypassed", False),
        "milestone": r.get("milestone"),
    }


def cmd_history(env: Env, args: Any) -> Outcome:
    cfg = env.config()
    items = [run_summary(r) for r in runs.list_runs(cfg.paths, args.limit)]
    st = env.style
    if not items:
        return Outcome(EXIT_OK, {"runs": []}, "no gate runs yet; run `sprint gate`")
    lines = [
        st.dim(
            f"{'when (UTC)':<17} {'result':<8} {'sprint':<6} {'tests':>6} {'fail':>5} {'miss':>5} {'skip+':>5}  agent / trigger"
        )
    ]
    for s in items:
        when = (s["timestamp"] or "")[:16].replace("T", " ")
        result = s["result"] or "?"
        sym = st.ok if result == "pass" else (st.warn if result == "bypassed" else st.bad)
        ms = st.dim(f"  [{s['milestone']}]") if s.get("milestone") else ""
        lines.append(
            f"{when:<17} {sym} {result:<6} {s['sprint'] or '-':<6} {s['total'] if s['total'] is not None else '-':>6} "
            f"{s['failed'] if s['failed'] is not None else '-':>5} {s['missing']:>5} {s['new_skips']:>5}  "
            f"{s['agent']} / {s['trigger']} {st.dim(s['head'] or '')}{ms}"
        )
    return Outcome(EXIT_OK, {"runs": items}, "\n".join(lines))


# --------------------------------------------------------------------------- status


def project_status(cfg: Config) -> dict[str, Any]:
    """Everything `status`, the dashboard and the SessionStart hook need."""
    sprints, sprint_errors = (
        load_sprints(cfg.paths.sprints, strict=False) if cfg.sprints_mode else ([], [])
    )
    latest = runs.load_latest(cfg.paths)
    base = bl.load_baseline(cfg.paths)
    head = gitutil.head(cfg.root)
    fp = gitutil.fingerprint(cfg.root)
    stale = None
    if latest:
        lg = latest.get("git") or {}
        if head and lg.get("head") and lg.get("head") != head:
            stale = "HEAD moved since the last gate run"
        elif fp and lg.get("fingerprint") and lg.get("fingerprint") != fp:
            stale = "files changed since the last gate run"
    current = next((s for s in sprints if s.id == cfg.sprint_current), None)
    acs_latest = {
        (a["sprint"], a["id"]): a
        for a in (latest or {}).get("acs_all", (latest or {}).get("acs", []))
    }
    acs = []
    if current:
        for ac in current.acs:
            hit = acs_latest.get((current.id, ac.id))
            acs.append(
                {
                    "id": ac.id,
                    "desc": ac.desc,
                    "tests": ac.tests,
                    "state": hit["state"] if hit else "no-tests",
                    "matched": len(hit.get("tests", [])) if hit else 0,
                    "failing": sum(1 for t in hit.get("tests", []) if t["outcome"] != "passed")
                    if hit
                    else 0,
                }
            )
    removals = bl.load_removals(cfg.paths)
    skips = bl.load_skips(cfg.paths)
    return {
        "project": cfg.name,
        "key": cfg.key,
        "root": str(cfg.root),
        "mode": cfg.mode,
        "stack": cfg.stack,
        "version": __version__,
        "sprint": current.to_json() | {"acs_state": acs} if current else None,
        "sprint_current": cfg.sprint_current or None,
        "sprints": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "started": s.started,
                "closed": s.closed,
            }
            for s in sprints
        ],
        "sprint_errors": sprint_errors,
        "latest": runs.cap_lists(latest, 50) if latest else None,
        "stale": stale,
        "baseline": base.summary() if base else None,
        "removals": len(bl.effective(removals, base)),
        "skips_allowed": len(bl.effective(skips, base)),
        "git": {"head": head, "branch": gitutil.branch(cfg.root) if head else None},
        "test_commands": [s.command for s in cfg.suites],
    }


def render_status(s: dict[str, Any], st: Style) -> str:
    lines = [st.bold(f"{s['project']} ({s['key']}) · {s['mode']} · {s['stack']}")]
    sp = s.get("sprint")
    if s["mode"] == "sprints":
        if sp:
            since = f" · active since {sp['started']}" if sp.get("started") else ""
            lines.append(f"Sprint {st.bold(sp['id'])} · {sp['title']}{since}")
            if sp.get("goal"):
                lines.append(f"Goal: {sp['goal']}")
            if sp["acs_state"]:
                lines.append("ACs:")
                for a in sp["acs_state"]:
                    sym = ac_symbol(a["state"], st)
                    extra = ""
                    if a["state"] == "no-tests":
                        extra = "no matching tests"
                    elif a["state"] == "failing":
                        extra = f"{plural(a['matched'], 'test')}, {a['failing']} not passing"
                    else:
                        extra = plural(a["matched"], "test")
                    lines.append(f"  {sym} {a['id']:<5} {a['desc']}  {st.dim('(' + extra + ')')}")
            if sp.get("out_of_scope"):
                lines.append(st.dim("Out of scope: " + ", ".join(sp["out_of_scope"])))
        else:
            planned = [x["id"] for x in s["sprints"] if x["status"] == "planned"]
            hint = (
                f"start one with `sprint start {planned[0]}`"
                if planned
                else "create one with `sprint new <title>`"
            )
            lines.append(f"No active sprint; {hint}")
    for err in s.get("sprint_errors") or []:
        lines.append(f"{st.bad} {err}")
    latest = s.get("latest")
    if latest:
        result = latest.get("result", "?")
        sym = st.ok if result == "pass" else st.bad
        when = (latest.get("timestamp") or "")[:16].replace("T", " ")
        head = ((latest.get("git") or {}).get("head") or "")[:7]
        stale = st.yellow(f" (stale: {s['stale']})") if s.get("stale") else st.dim(" (current)")
        lines.append(
            f"Last gate: {sym} {result.upper()} · {when} UTC · {latest.get('agent')} · {head}{stale}"
        )
        c = latest.get("counts") or {}
        bits = []
        if c.get("regressions"):
            bits.append(st.red(plural(c["regressions"], "regression")))
        if c.get("failing"):
            bits.append(f"{c['failing']} failing")
        if c.get("missing"):
            bits.append(f"{c['missing']} missing")
        if c.get("new_skips"):
            bits.append(plural(c["new_skips"], "new skip"))
        if bits:
            lines.append("  " + ", ".join(bits) + st.dim("  (details: `sprint gate --no-run`)"))
        per_sprint: dict[str, int] = {}
        for f in latest.get("failing") or []:
            if f.get("regression"):
                per_sprint[f["sprint"]] = per_sprint.get(f["sprint"], 0) + 1
        if per_sprint:
            parts = [f"{k} ×{per_sprint[k]}" for k in sort_sprint_keys(per_sprint)]
            lines.append("  " + st.red("regressions by sprint: " + ", ".join(parts)))
        by = latest.get("by_sprint") or {}
        if by:
            parts = [
                f"{k} {v.get('total', 0)}" for k, v in ((k, by[k]) for k in sort_sprint_keys(by))
            ]
            total = (latest.get("totals") or {}).get("total", 0)
            lines.append(f"Tests: {total} · " + " · ".join(parts))
    else:
        lines.append("Last gate: none yet (run `sprint gate`)")
    b = s.get("baseline")
    if b:
        when = (b.get("created") or "")[:10]
        lines.append(
            f"Baseline: {b['total']} tests · {when} · {b.get('reason') or ''}".rstrip(" ·")
        )
    else:
        lines.append("Baseline: none (run `sprint baseline` on a clean, passing tree)")
    if s.get("removals") or s.get("skips_allowed"):
        lines.append(
            st.dim(
                f"Accepted since baseline: {plural(s['removals'], 'removal')}, {plural(s['skips_allowed'], 'skip')}"
            )
        )
    return "\n".join(lines)


def cmd_status(env: Env, args: Any) -> Outcome:
    cfg = env.config()
    s = project_status(cfg)
    return Outcome(EXIT_OK, s, render_status(s, env.style))


def cmd_export(env: Env, args: Any) -> Outcome:
    cfg = env.config()
    s = project_status(cfg)
    s["sprints_full"] = (
        [x.to_json() for x in load_sprints(cfg.paths.sprints, strict=False)[0]]
        if cfg.sprints_mode
        else []
    )
    s["latest_full"] = runs.load_latest(cfg.paths)
    s["history"] = [run_summary(r) for r in runs.list_runs(cfg.paths, 100)]
    s["removals_list"] = [a.to_json() for a in bl.load_removals(cfg.paths)]
    s["skips_list"] = [a.to_json() for a in bl.load_skips(cfg.paths)]
    if args.format == "markdown":
        latest = s["latest_full"]
        text = render_markdown(latest) if latest else "No gate runs yet.\n"
        return Outcome(EXIT_OK, s, text)
    import json

    return Outcome(EXIT_OK, s, json.dumps(s, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- doctor


def cmd_doctor(env: Env, args: Any) -> Outcome:
    st = env.style
    checks: list[tuple[str, str, str]] = []  # (level ok|warn|error, title, detail)

    def add(level: str, title: str, detail: str = "") -> None:
        checks.append((level, title, detail))

    root = find_root(env.cwd)
    if root is None:
        add(
            "error",
            "no .sprint/config.toml found",
            "run `sprint init --ratchet-only` at the repo root",
        )
        return _doctor_outcome(checks, st)
    add("ok", f"project root {root}")
    try:
        cfg = load_config(root)
        add("ok", f"config.toml parses (mode {cfg.mode}, stack {cfg.stack})")
        for w in cfg.warnings:
            add("warn", f"config: {w}")
    except SprintError as exc:
        add("error", f"config.toml: {exc}", exc.hint)
        return _doctor_outcome(checks, st)

    for suite in cfg.suites:
        first = (
            suite.effective_command().strip().split()[0]
            if suite.effective_command().strip()
            else ""
        )
        exe = first if first not in ("npx", "./gradlew", "gradlew.bat") else first
        if first.startswith("./"):
            ok = (cfg.root / suite.cwd / first[2:]).exists()
        else:
            ok = shutil.which(exe) is not None
        add(
            "ok" if ok else "warn",
            f"suite {suite.name!r}: `{suite.effective_command()}`",
            "" if ok else f"`{first}` was not found on PATH (fine if your shell provides it)",
        )
        from sprintwarden.globs import find_files

        files = find_files(cfg.root, suite.reports)
        if files:
            add(
                "ok",
                f"suite {suite.name!r}: {plural(len(files), 'report file')} match {', '.join(suite.reports)}",
            )
        else:
            add(
                "warn",
                f"suite {suite.name!r}: no files match {', '.join(suite.reports)} yet",
                "normal before the first `sprint gate`; otherwise check [test] reports",
            )

    if cfg.sprints_mode:
        sprints, errors = load_sprints(cfg.paths.sprints, strict=False)
        for e in errors:
            add("error", e)
        problems = validate_sprints(sprints, cfg.sprint_current)
        for p in problems:
            add("error" if "active" in p or "current" in p else "warn", p)
        if sprints and not errors and not problems:
            add(
                "ok",
                f"{plural(len(sprints), 'sprint file')} valid; current {cfg.sprint_current or 'none'}",
            )
        if not sprints:
            add("warn", "no sprint files", "create one with `sprint new <title>`")

    for label, loader in (
        ("baseline.json", bl.load_baseline),
        ("removals.json", bl.load_removals),
        ("skips.json", bl.load_skips),
    ):
        try:
            value = loader(cfg.paths)
            if label == "baseline.json":
                if value is None:
                    add("warn", "no baseline yet", "run `sprint baseline` on a clean, passing tree")
                else:
                    add(
                        "ok",
                        f"baseline: {value.total} tests ({value.created[:10]}, {value.reason})",
                    )
            else:
                add("ok", f"{label}: {len(value)} entries")
        except SprintError as exc:
            add("error", str(exc))

    latest = runs.load_latest(cfg.paths)
    if latest is None and cfg.paths.latest.exists():
        add(
            "error",
            "latest.json is unreadable (merge conflict?)",
            "take either side and re-run `sprint gate`",
        )

    if gitutil.is_repo(cfg.root):
        add("ok", "git repository")
        ignore = read_text(cfg.root / ".gitignore") or ""
        if ".sprint/out" not in ignore:
            add("warn", ".sprint/out/ is not gitignored", "run `sprint init` again to fix")
        if cfg.git_pre_push:
            hooks = gitutil.hooks_dir(cfg.root)
            hp = gitutil.hooks_path_config(cfg.root) or ""
            target = (
                (cfg.root / ".husky" / "pre-push")
                if ".husky" in hp
                else (hooks / "pre-push" if hooks else None)
            )
            text = read_text(target) if target else None
            if text and (project.HOOK_MARKER in text or "sprint hook pre-push" in text):
                add("ok", "pre-push hook installed")
            else:
                add(
                    "warn",
                    "pre-push hook not installed",
                    "run `sprint init` again (or set hooks.git_pre_push = false)",
                )
    else:
        add(
            "warn",
            "not a git repository",
            "clean-HEAD checks, tags and the pre-push hook are disabled",
        )

    if cfg.claude_stop_hook:
        settings = read_text(cfg.root / ".claude" / "settings.json") or ""
        if project.STOP_CMD in settings:
            add("ok", "Claude Code Stop hook configured")
        else:
            add(
                "warn",
                "Claude Code Stop hook missing from .claude/settings.json",
                "run `sprint init` again, or install the sprintwarden Claude Code plugin",
            )
    if shutil.which("sprint") is None:
        add(
            "warn",
            "`sprint` is not on PATH",
            "hooks call `sprint`; install with `pipx install sprintwarden`",
        )
    try:
        if cfg.root.resolve() in registry.load():
            add("ok", "registered for the dashboard")
        else:
            add("warn", "not in the global registry", "run `sprint register`")
    except SprintError as exc:
        add("warn", str(exc))
    agents = read_text(cfg.root / "AGENTS.md") or ""
    if project.BEGIN not in agents:
        add("warn", "AGENTS.md has no sprintwarden rules", "run `sprint init` again")
    return _doctor_outcome(checks, st)


def _doctor_outcome(checks: list[tuple[str, str, str]], st: Style) -> Outcome:
    sym = {"ok": st.ok, "warn": st.warn, "error": st.bad}
    lines = []
    for level, title, detail in checks:
        lines.append(f"{sym[level]} {title}")
        if detail and level != "ok":
            lines.append(st.dim(f"     {detail}"))
    errors = sum(1 for c in checks if c[0] == "error")
    warns = sum(1 for c in checks if c[0] == "warn")
    lines.append(
        "doctor: " + (f"{plural(errors, 'error')}, " if errors else "") + plural(warns, "warning")
    )
    data = {
        "checks": [{"level": c[0], "title": c[1], "detail": c[2]} for c in checks],
        "errors": errors,
        "warnings": warns,
    }
    return Outcome(EXIT_USAGE if errors else EXIT_OK, data, "\n".join(lines))


# --------------------------------------------------------------------------- registry


def cmd_register(env: Env, args: Any) -> Outcome:
    path = Path(args.path).resolve() if args.path else env.root()
    if not (path / SPRINT_DIR / "config.toml").is_file():
        raise SprintError(f"{path} is not a sprintwarden project")
    added = registry.register(path)
    msg = f"registered {path}" if added else f"{path} is already registered"
    return Outcome(EXIT_OK, {"path": str(path), "added": added}, msg)


def cmd_unregister(env: Env, args: Any) -> Outcome:
    path = Path(args.path).resolve() if args.path else (find_root(env.cwd) or env.cwd.resolve())
    removed = registry.unregister(path)
    msg = f"unregistered {path}" if removed else f"{path} was not registered"
    return Outcome(EXIT_OK, {"path": str(path), "removed": removed}, msg)
