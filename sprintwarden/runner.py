"""Run the configured test command(s). sprintwarden never talks to a test
framework directly: it runs a shell command and reads the JUnit XML it leaves."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from sprintwarden import gitutil
from sprintwarden.config import Config, Suite
from sprintwarden.globs import find_files

TAIL_LINES = 40


@dataclass
class RunnerResult:
    suite: str
    command: str
    exit_code: int | None
    duration_s: float
    timed_out: bool = False
    error: str = ""
    tail: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "suite": self.suite,
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 2),
            "timed_out": self.timed_out,
            "error": self.error,
        }


def _looks_like_junit(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return b"<testsuite" in head


def clean_reports(cfg: Config) -> list[str]:
    """Delete stale report files before a run so a deleted test can't hide behind
    an old XML file. Only removes files that look like JUnit XML and are not
    tracked by git, so a careless glob can never delete source files."""
    files = [p for p in find_files(cfg.root, cfg.report_globs) if _looks_like_junit(p)]
    if not files:
        return []
    tracked = gitutil.tracked_files(cfg.root, files)
    removed = []
    for p in files:
        if gitutil.path_key(p) in tracked:
            continue
        try:
            p.unlink()
            removed.append(str(p))
        except OSError:
            continue
    return removed


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_suite(
    cfg: Config,
    suite: Suite,
    log: TextIO,
    *,
    echo: TextIO | None = None,
) -> RunnerResult:
    command = suite.effective_command()
    cwd = (cfg.root / suite.cwd).resolve() if suite.cwd else cfg.root
    env = dict(os.environ)
    env.update(suite.env)
    env["SPRINT_GATE"] = "1"
    (cfg.root / ".sprint" / "out").mkdir(parents=True, exist_ok=True)
    log.write(f"$ {command}\n")
    log.flush()
    start = time.monotonic()
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
    except OSError as exc:
        return RunnerResult(suite.name, command, None, 0.0, error=f"could not start: {exc}")

    tail: deque[str] = deque(maxlen=TAIL_LINES)

    def pump() -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace")
            log.write(line)
            tail.append(line.rstrip("\r\n"))
            if echo is not None:
                echo.write(line)
                echo.flush()
        proc.stdout.close()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    timeout = suite.timeout_minutes * 60 if suite.timeout_minutes else None
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        proc.wait()
    except KeyboardInterrupt:
        _kill_tree(proc)
        raise
    reader.join(timeout=10)
    duration = time.monotonic() - start
    log.write(f"[exit {proc.returncode} after {duration:.1f}s]\n")
    log.flush()
    error = f"timed out after {suite.timeout_minutes:g} min" if timed_out else ""
    return RunnerResult(
        suite.name,
        command,
        proc.returncode,
        duration,
        timed_out=timed_out,
        error=error,
        tail=list(tail),
    )


def run_all(cfg: Config, *, verbose: bool = False) -> list[RunnerResult]:
    log_path = cfg.paths.runner_log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        for suite in cfg.suites:
            results.append(run_suite(cfg, suite, log, echo=sys.stderr if verbose else None))
    return results
