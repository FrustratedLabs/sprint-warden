"""Run every example through the sprint story and assert the outcomes.

For each example (in a throwaway copy with its own git repo):

1. ``sprint init`` writes the baseline from the passing suite;
2. on ``main`` the gate passes and the active sprint's ACs are satisfied;
3. on ``s01-regression`` (files from ``.regression/``) the gate fails, and the
   failure is labelled "REGRESSION from sprint S01";
4. on ``agent-cheat`` (files from ``.cheat/``, if present) deleting the failing
   S01 test is caught as "missing vs baseline";
5. back on ``main`` the gate passes again.

    python examples/run_all.py [pytest vitest go gradle] [--keep] [--json]

Stacks whose toolchain isn't installed are reported as SKIP, not failures.
With ``--keep`` the projects stay registered in a temporary SPRINT_HOME, so
``sprint ui`` can show them (the command to run is printed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
IGNORE = shutil.ignore_patterns(
    ".regression",
    ".cheat",
    "node_modules",
    "build",
    ".gradle",
    "out",
    "__pycache__",
    ".pytest_cache",
)


@dataclass
class Example:
    name: str
    folder: str
    tools: list[str]
    regression_hint: str  # substring of the S01 test that the regression breaks
    setup: list[list[str]] = field(default_factory=list)


EXAMPLES = {
    "pytest": Example("pytest", "pytest-invoices", [], "test_S01_rounds_half_up"),
    "vitest": Example(
        "vitest",
        "vitest-cart",
        ["node", "npm"],
        "[S01] cart totals",
        setup=[["npm", "ci", "--no-audit", "--no-fund", "--loglevel=error"]],
    ),
    "go": Example("go", "go-shapes", ["go"], "Test_S01_CircleArea"),
    "gradle": Example("gradle", "gradle-library", ["java"], "S01_fahrenheitToCelsius"),
}


class Failure(Exception):
    pass


def sh(
    cmd: list[str], cwd: Path, env: dict[str, str], *, check: bool = True
) -> subprocess.CompletedProcess:
    if os.name == "nt" and cmd and cmd[0] in ("npm", "npx"):
        cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and proc.returncode != 0:
        raise Failure(
            f"{' '.join(cmd)} failed ({proc.returncode}):\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
        )
    return proc


def sprint(args: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, dict]:
    proc = sh([sys.executable, "-m", "sprintwarden", *args, "--json"], cwd, env, check=False)
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {"raw": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    return proc.returncode, data


def overlay(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        if path.is_file():
            target = dst / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def ensure_go_junit_report(env: dict[str, str], bin_dir: Path) -> None:
    if shutil.which("go-junit-report", path=env["PATH"]):
        return
    bin_dir.mkdir(parents=True, exist_ok=True)
    install_env = dict(env, GOBIN=str(bin_dir))
    sh(["go", "install", "github.com/jstemmer/go-junit-report/v2@latest"], bin_dir, install_env)


def expect(cond: bool, message: str, data: object = None) -> None:
    if not cond:
        detail = json.dumps(data, indent=1)[-3000:] if data is not None else ""
        raise Failure(f"{message}\n{detail}")


def checks(rec: dict) -> dict:
    return {c["id"]: c for c in rec.get("checks", [])}


def run_example(ex: Example, work: Path, env: dict[str, str]) -> list[str]:
    steps: list[str] = []
    src = HERE / ex.folder
    proj = work / ex.folder
    shutil.copytree(src, proj, ignore=IGNORE)
    git = lambda *a: sh(["git", *a], proj, env)  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "examples@example.invalid")
    git("config", "user.name", "examples")
    git("config", "commit.gpgsign", "false")
    for cmd in ex.setup:
        sh(cmd, proj, env)
    git("add", "-A")
    git("commit", "-q", "-m", "S01 + S02")

    code, data = sprint(["init", "--yes", "--no-hooks"], proj, env)
    expect(code == 0 and data.get("baseline"), "init should write the baseline", data)
    steps.append(f"init: baseline of {data['baseline']['total']} tests")
    git("add", "-A")
    git("commit", "-q", "-m", "add sprintwarden")

    code, rec = sprint(["gate"], proj, env)
    expect(code == 0 and rec.get("result") == "pass", "gate should pass on main", rec)
    acs = rec.get("acs", [])
    expect(
        acs and all(a["state"] == "satisfied" for a in acs),
        "S02 ACs should be satisfied on main",
        acs,
    )
    steps.append(f"main: PASS, {len(acs)}/{len(acs)} S02 ACs satisfied")

    git("checkout", "-q", "-b", "s01-regression")
    overlay(src / ".regression", proj)
    git("commit", "-q", "-am", "S02: refactor (breaks S01)")
    code, rec = sprint(["gate"], proj, env)
    regs = [f for f in rec.get("failing", []) if f.get("regression") and f["sprint"] == "S01"]
    expect(code == 1 and rec.get("result") == "fail", "gate should fail on s01-regression", rec)
    expect(
        any(ex.regression_hint in f["id"] for f in regs),
        f"an S01 regression on {ex.regression_hint}",
        rec,
    )
    expect(
        all(f.get("regression_reason") == "from sprint S01" for f in regs),
        "labelled 'from sprint S01'",
        regs,
    )
    steps.append(f"s01-regression: FAIL, REGRESSION from sprint S01 ({regs[0]['id']})")

    if (src / ".cheat").is_dir():
        git("checkout", "-q", "main")
        git("checkout", "-q", "-b", "agent-cheat")
        overlay(src / ".regression", proj)
        overlay(src / ".cheat", proj)
        git("commit", "-q", "-am", "S02: make the build green")
        code, rec = sprint(["gate"], proj, env)
        missing = [m["id"] for m in rec.get("missing", [])]
        expect(
            code == 1 and any(ex.regression_hint in m for m in missing),
            "deleting the S01 test is caught",
            rec,
        )
        expect(not rec.get("failing"), "the remaining tests pass (the cheat 'worked')", rec)
        steps.append(f"agent-cheat: FAIL, missing vs baseline ({missing[0]})")

    git("checkout", "-q", "main")
    code, rec = sprint(["gate"], proj, env)
    expect(code == 0, "gate should pass again on main", rec)
    steps.append("main again: PASS")
    return steps


def available(ex: Example) -> str | None:
    missing = [t for t in ex.tools if shutil.which(t) is None]
    return f"needs {', '.join(missing)}" if missing else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stacks", nargs="*", default=list(EXAMPLES))
    ap.add_argument(
        "--keep", action="store_true", help="keep the projects and print the `sprint ui` command"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable results")
    ap.add_argument(
        "--require", action="store_true", help="treat a missing toolchain as a failure (CI)"
    )
    args = ap.parse_args(argv)
    unknown = [s for s in args.stacks if s not in EXAMPLES]
    if unknown:
        ap.error(f"unknown example(s): {', '.join(unknown)} (known: {', '.join(EXAMPLES)})")

    work = Path(tempfile.mkdtemp(prefix="sprintwarden-examples-"))
    env = dict(os.environ)
    for var in (
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_CHILD_SESSION",
        "AI_AGENT",
        "SPRINT_SKIP",
    ):
        env.pop(var, None)
    env.update(
        SPRINT_HOME=str(work / "home"),
        SPRINT_AGENT="examples",
        NO_COLOR="1",
        PYTHONPATH=str(REPO) + os.pathsep + env.get("PYTHONPATH", ""),
        PATH=os.pathsep.join(
            [str(work / "bin"), str(Path(sys.executable).parent), env.get("PATH", "")]
        ),
    )
    results: dict[str, dict] = {}
    for name in args.stacks:
        ex = EXAMPLES[name]
        reason = available(ex)
        if reason and not args.require:
            results[name] = {"status": "skip", "reason": reason}
            continue
        try:
            if name == "go":
                ensure_go_junit_report(env, work / "bin")
            steps = run_example(ex, work, env)
            results[name] = {"status": "pass", "steps": steps}
        except Failure as exc:
            results[name] = {"status": "fail", "error": str(exc)}
    failed = [n for n, r in results.items() if r["status"] == "fail"]
    if args.json:
        print(
            json.dumps(
                {"results": results, "work": str(work), "sprint_home": env["SPRINT_HOME"]}, indent=1
            )
        )
    else:
        for name, r in results.items():
            mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[r["status"]]
            print(f"[{mark}] {name}")
            for step in r.get("steps", []):
                print(f"         {step}")
            if r["status"] == "skip":
                print(f"         ({r['reason']})")
            if r["status"] == "fail":
                print("         " + r["error"].replace("\n", "\n         "))
        if args.keep:
            print(
                f"\nProjects kept in {work}. View them:\n  SPRINT_HOME={env['SPRINT_HOME']} sprint ui --open"
            )
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
