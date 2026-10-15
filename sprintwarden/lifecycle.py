"""Sprint lifecycle: ``new``, ``start``, ``park``/``unpark``, ``close`` and ``note``.

"Done" is computed, never ticked: ``close`` refuses unless the gate passes on a
clean HEAD and every acceptance criterion is satisfied by passing tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sprintwarden import agentdetect, gitutil, project, runs
from sprintwarden import baseline as bl
from sprintwarden.commands import Env, Outcome, guard_human
from sprintwarden.config import Config, load_config, set_value
from sprintwarden.gate import load_full, run_gate
from sprintwarden.report import ac_symbol, render_gate
from sprintwarden.sprintfile import (
    Sprint,
    active_sprint,
    append_note,
    find_sprint,
    load_sprints,
    next_sprint_id,
    raw_literal,
    render_sprint,
    set_fields,
    sprint_filename,
)
from sprintwarden.stacks import load_stacks
from sprintwarden.util import (
    EXIT_GATE_FAIL,
    EXIT_OK,
    SprintError,
    plural,
    read_text,
    today,
    write_text,
)


def _sprints_cfg(env: Env) -> Config:
    cfg = env.config()
    if not cfg.sprints_mode:
        raise SprintError(
            "this project is in ratchet-only mode",
            hint='set project.mode = "sprints" in .sprint/config.toml to use sprints',
        )
    return cfg


def _example(cfg: Config) -> str:
    stack = load_stacks().get(cfg.stack)
    return stack.example_test if stack else "S01_doesThing"


def cmd_new(env: Env, args: Any) -> Outcome:
    cfg = _sprints_cfg(env)
    sprints, _ = load_sprints(cfg.paths.sprints)
    sid = next_sprint_id(sprints)
    title = " ".join(args.title).strip()
    if not title:
        raise SprintError("give the sprint a title")
    cfg.paths.sprints.mkdir(parents=True, exist_ok=True)
    path = cfg.paths.sprints / sprint_filename(sid, title)
    if path.exists():
        raise SprintError(f"{path} already exists")
    write_text(
        path, render_sprint(sid, title, goal=args.goal, status="planned", example=_example(cfg))
    )
    rel = path.relative_to(cfg.root).as_posix()
    text = (
        f"{env.style.ok} created {rel} (planned)\n"
        f"Edit its goal and acceptance criteria, then `sprint start {sid}`."
    )
    return Outcome(EXIT_OK, {"id": sid, "path": rel, "title": title}, text)


def cmd_start(env: Env, args: Any) -> Outcome:
    cfg = _sprints_cfg(env)
    sprints, _ = load_sprints(cfg.paths.sprints)
    sprint = find_sprint(sprints, args.id)
    if sprint is None:
        raise SprintError(
            f"no sprint {args.id} in .sprint/sprints/", hint="create one with `sprint new <title>`"
        )
    if sprint.status == "closed":
        raise SprintError(
            f"{sprint.id} is closed", hint="create a new sprint with `sprint new <title>`"
        )
    active = active_sprint(sprints)
    if active and active.id != sprint.id:
        raise SprintError(
            f"{active.id} is active", hint=f"close it first: `sprint close {active.id}` (human)"
        )
    text = read_text(sprint.path) or ""
    fields: dict[str, Any] = {"status": "active", **_unpark_fields(sprint)}
    if not sprint.started:
        fields["started"] = raw_literal(today())
    write_text(sprint.path, set_fields(text, **fields))
    set_value(cfg.root, "sprint", "current", sprint.id)
    cfg = load_config(cfg.root)
    project.write_agents_md(cfg, _example(cfg), refresh=True)
    msg = f"{env.style.ok} {sprint.id} ({sprint.title}) is active; config sprint.current = {sprint.id}"
    if not sprint.acs or all(not ac.tests for ac in sprint.acs):
        msg += f"\n{env.style.warn} no AC lists tests yet; edit {sprint.path.name} so 'done' can be computed"
    return Outcome(EXIT_OK, {"id": sprint.id, "title": sprint.title}, msg)


def _unpark_fields(sprint: Sprint) -> dict[str, Any]:
    """Clear the parked markers, but don't add empty keys to files that never had them."""
    fields: dict[str, Any] = {}
    if sprint.parked:
        fields["parked"] = ""
    if sprint.parked_reason:
        fields["parked_reason"] = ""
    return fields


def _find_or_fail(cfg: Config, sprint_id: str) -> tuple[list[Sprint], Sprint]:
    sprints, _ = load_sprints(cfg.paths.sprints)
    sprint = find_sprint(sprints, sprint_id)
    if sprint is None:
        raise SprintError(f"no sprint {sprint_id} in .sprint/sprints/")
    return sprints, sprint


def cmd_park(env: Env, args: Any) -> Outcome:
    """Set a planned or active sprint aside. Its tests stay in the ratchet."""
    cfg = _sprints_cfg(env)
    _, sprint = _find_or_fail(cfg, args.id)
    if sprint.status == "closed":
        raise SprintError(f"{sprint.id} is closed; a done sprint can't be parked")
    if sprint.status == "parked":
        return Outcome(
            EXIT_OK,
            {"id": sprint.id, "status": "parked", "changed": False},
            f"{env.style.ok} {sprint.id} is already parked",
        )
    reason = " ".join((args.reason or "").split())
    was_active = sprint.status == "active"
    text = set_fields(
        read_text(sprint.path) or "",
        status="parked",
        parked=raw_literal(today()),
        parked_reason=reason,
    )
    note = f"Parked{' (was active)' if was_active else ''}" + (f": {reason}" if reason else "")
    write_text(sprint.path, append_note(text, note, date=today(), agent=agentdetect.detect()))
    lines = [f"{env.style.ok} {sprint.id} ({sprint.title}) is parked"]
    if was_active and cfg.sprint_current == sprint.id:
        set_value(cfg.root, "sprint", "current", "")
        cfg = load_config(cfg.root)
        project.write_agents_md(cfg, _example(cfg), refresh=True)
        lines.append("No sprint is active now; `sprint start <id>` picks the next one.")
    lines.append(f"Its tests stay in the ratchet. Bring it back with `sprint unpark {sprint.id}`.")
    data = {
        "id": sprint.id,
        "status": "parked",
        "changed": True,
        "was": "active" if was_active else "planned",
    }
    return Outcome(EXIT_OK, data, "\n".join(lines))


def cmd_unpark(env: Env, args: Any) -> Outcome:
    """Move a parked sprint back to planned (or `sprint start` it directly)."""
    cfg = _sprints_cfg(env)
    _, sprint = _find_or_fail(cfg, args.id)
    if sprint.status != "parked":
        raise SprintError(f"{sprint.id} is {sprint.status}, not parked")
    text = set_fields(read_text(sprint.path) or "", status="planned", **_unpark_fields(sprint))
    since = f" since {sprint.parked}" if sprint.parked else ""
    write_text(
        sprint.path,
        append_note(
            text, f"Back to planned (was parked{since})", date=today(), agent=agentdetect.detect()
        ),
    )
    return Outcome(
        EXIT_OK,
        {"id": sprint.id, "status": "planned"},
        f"{env.style.ok} {sprint.id} ({sprint.title}) is planned again; `sprint start {sprint.id}` when it's next",
    )


def add_note(cfg: Config, text: str, *, agent: str | None = None) -> Path:
    if not cfg.sprints_mode:
        raise SprintError("notes need sprints mode (ratchet-only projects have no sprint files)")
    sprints, _ = load_sprints(cfg.paths.sprints)
    sprint = active_sprint(sprints)
    if sprint is None:
        raise SprintError("no active sprint to add a note to")
    text = " ".join(text.split())
    if len(text) < 3:
        raise SprintError("the note is empty")
    body = read_text(sprint.path) or ""
    write_text(
        sprint.path, append_note(body, text, date=today(), agent=agent or agentdetect.detect())
    )
    return sprint.path


def cmd_note(env: Env, args: Any) -> Outcome:
    cfg = env.config()
    agent = agentdetect.detect()
    path = add_note(cfg, " ".join(args.text), agent=agent)
    rel = path.relative_to(cfg.root).as_posix()
    return Outcome(
        EXIT_OK, {"path": rel, "agent": agent}, f"{env.style.ok} noted in {rel} (agent: {agent})"
    )


# --------------------------------------------------------------------------- close


def _changelog_entry(
    sprint: Sprint,
    acs: list[dict[str, Any]],
    total: int,
    added: int,
    tag: str | None,
    *,
    level: str,
) -> str:
    lines = [f"{level} Sprint {sprint.id}: {sprint.title} ({today()})", ""]
    if sprint.goal:
        lines += [f"Goal: {sprint.goal}", ""]
    for a in acs:
        lines.append(f"- {a['id']}: {a['desc']}")
    if acs:
        lines.append("")
    tail = f"Tests: {total} ({'+' if added >= 0 else ''}{added} since the previous baseline)"
    if tag:
        tail += f" · tag `{tag}`"
    lines += [tail, ""]
    return "\n".join(lines)


def update_changelog(root: Path, entry_for_level) -> str:
    """Insert newest-first: under ``## [Unreleased]`` if present, else before the first ``## ``."""
    path = root / "CHANGELOG.md"
    text = read_text(path)
    if text is None:
        write_text(path, "# Changelog\n\n" + entry_for_level("##"))
        return "created CHANGELOG.md"
    lines = text.splitlines(keepends=True)
    unreleased = next(
        (i for i, line in enumerate(lines) if re.match(r"^##\s+\[?unreleased\]?", line, re.I)), None
    )
    if unreleased is not None:
        lines.insert(unreleased + 1, "\n" + entry_for_level("###"))
    else:
        first = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
        block = entry_for_level("##") + "\n"
        if first is None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append("\n" + entry_for_level("##"))
        else:
            lines.insert(first, block)
    write_text(path, "".join(lines))
    return "updated CHANGELOG.md"


def cmd_close(env: Env, args: Any) -> Outcome:
    by = guard_human("close", args)
    cfg = _sprints_cfg(env)
    sprints, _ = load_sprints(cfg.paths.sprints)
    sprint = find_sprint(sprints, args.id)
    if sprint is None:
        raise SprintError(f"no sprint {args.id}")
    if sprint.status != "active" or cfg.sprint_current != sprint.id:
        raise SprintError(f"{sprint.id} is not the active, current sprint")
    if gitutil.is_dirty(cfg.root):
        raise SprintError(
            "the working tree has uncommitted changes",
            hint="commit or stash them first: a sprint closes on a clean HEAD",
        )
    is_repo = gitutil.is_repo(cfg.root)
    tag = None if args.no_tag or not is_repo else f"sprint-{sprint.id}"
    if tag and gitutil.tag_exists(cfg.root, tag):
        raise SprintError(f"git tag {tag} already exists")

    st = env.style
    record: dict[str, Any] | None = None
    tests: dict[str, str] | None = None
    if args.no_run:
        full = load_full(cfg)
        latest = runs.load_latest(cfg.paths)
        fp = gitutil.fingerprint(cfg.root)
        if (
            full
            and latest
            and fp
            and full.get("fingerprint") == fp
            and latest.get("id") == full.get("id")
        ):
            record, tests = latest, full.get("tests") or {}
        else:
            raise SprintError(
                "the latest gate run doesn't match this tree", hint="run without --no-run"
            )
    else:
        result = run_gate(cfg, trigger="close")
        record = result.record
        tests = {t.id: t.outcome for t in result.context.tests.values()}

    report = render_gate(record, st)
    if record["result"] != "pass":
        return Outcome(
            EXIT_GATE_FAIL,
            {"gate": record, "closed": False},
            report + f"\n{st.bad} not closed: the gate fails",
        )
    acs = record.get("acs") or []
    unsatisfied = [a for a in acs if a["state"] != "satisfied"]
    if not acs:
        return Outcome(
            EXIT_GATE_FAIL,
            {"gate": record, "closed": False},
            report
            + f"\n{st.bad} not closed: {sprint.id} has no acceptance criteria, so 'done' can't be computed",
        )
    if unsatisfied:
        lines = [
            report,
            f"{st.bad} not closed: {plural(len(unsatisfied), 'acceptance criterion', 'acceptance criteria')} not satisfied",
        ]
        for a in unsatisfied:
            why = (
                "no matching tests" if a["state"] == "no-tests" else "matching tests don't all pass"
            )
            lines.append(f"     {ac_symbol(a['state'], st)} {a['id']} {a['desc']} ({why})")
        return Outcome(
            EXIT_GATE_FAIL,
            {"gate": record, "closed": False, "unsatisfied": unsatisfied},
            "\n".join(lines),
        )

    old = bl.load_baseline(cfg.paths)
    new = bl.write_baseline(
        cfg.paths,
        tests,
        reason=f"close {sprint.id}",
        sprint=sprint.id,
        git=record.get("git") or {},
        run=record.get("id"),
    )
    runs.mark_milestone(cfg.paths, record["id"], f"close {sprint.id}")
    write_text(
        sprint.path,
        set_fields(read_text(sprint.path) or "", status="closed", closed=raw_literal(today())),
    )
    set_value(cfg.root, "sprint", "current", "")
    added = new.total - (old.total if old else 0)
    changelog = update_changelog(
        cfg.root, lambda level: _changelog_entry(sprint, acs, new.total, added, tag, level=level)
    )
    lines = [
        report,
        f"{st.ok} {sprint.id} closed: all {plural(len(acs), 'AC')} satisfied by passing tests",
    ]
    lines.append(
        f"{st.ok} baseline: {plural(new.total, 'test')} ({'+' if added >= 0 else ''}{added})"
    )
    lines.append(f"{st.ok} {changelog}")
    commit = None
    if is_repo and not args.no_commit:
        message = (
            f"sprint: close {sprint.id} ({sprint.title})\n\n"
            + (f"Goal: {sprint.goal}\n" if sprint.goal else "")
            + "".join(f"- {a['id']}: {a['desc']}\n" for a in acs)
            + f"\nBaseline: {new.total} tests. Closed by: {by}.\n"
        )
        commit = gitutil.commit_paths(cfg.root, [".sprint", "CHANGELOG.md"], message)
        if commit:
            lines.append(f"{st.ok} committed {commit[:10]}")
    if tag:
        gitutil.create_tag(cfg.root, tag, f"Sprint {sprint.id}: {sprint.title}")
        note = "" if commit else " (on HEAD; the closing changes are not committed)"
        lines.append(f"{st.ok} tagged {tag}{note}")
    planned = [s for s in sprints if s.status == "planned"]
    lines.append(
        f"Next: `sprint start {planned[0].id}`" if planned else "Next: `sprint new <title>`"
    )
    data = {
        "gate": record,
        "closed": True,
        "id": sprint.id,
        "baseline": new.summary(),
        "tag": tag,
        "commit": commit,
        "by": by,
    }
    return Outcome(EXIT_OK, data, "\n".join(lines))
