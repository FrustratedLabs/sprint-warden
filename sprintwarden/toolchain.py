"""Run the test command with the project's own toolchain.

Hooks, git and CI start the gate with whatever PATH they inherited, so a bare
``python`` in the test command can be the wrong interpreter: Python 2, none at
all, or a Python 3 without the project's dependencies. Before running a suite we
put the project's virtualenv first on PATH, as if it were activated, and check
that a leading ``python`` is really there and is Python 3.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sprintwarden.config import Config

BIN = "Scripts" if os.name == "nt" else "bin"
PYTHONS = ("python", "python3")
FIX_HINT = (
    "Create the project's virtualenv (`python3 -m venv .venv` and install the test "
    "dependencies into it); sprintwarden uses .venv/ automatically. Or set "
    "test.path in .sprint/config.toml to the folder that has the right `python`."
)


@dataclass
class Toolchain:
    env: dict[str, str]
    prepended: list[tuple[str, str]] = field(default_factory=list)  # (folder, why)
    venv: str = ""


def _is_venv(folder: Path) -> bool:
    return (folder / "pyvenv.cfg").is_file() and (folder / BIN).is_dir()


def find_venv(root: Path, env: dict[str, str]) -> Path | None:
    """The project's virtualenv: ``.venv/``, then ``venv/``, then ``$VIRTUAL_ENV``."""
    for name in (".venv", "venv"):
        if _is_venv(root / name):
            return root / name
    active = env.get("VIRTUAL_ENV")
    if active and _is_venv(Path(active)):
        return Path(active)
    return None


def tilde(path: str) -> str:
    """``~/...`` instead of the home folder, so run logs don't carry the username."""
    home = str(Path.home())
    return "~" + path[len(home) :] if home and path.startswith(home) else path


def _show(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return tilde(str(path))


def build(cfg: Config, base: dict[str, str] | None = None) -> Toolchain:
    """The environment the test command runs in."""
    env = dict(os.environ if base is None else base)
    front: list[tuple[Path, str]] = [(cfg.root / p, "test.path") for p in cfg.test_path]
    venv = find_venv(cfg.root, env) if cfg.use_venv else None
    if venv is not None:
        front.append((venv / BIN, "project virtualenv"))
        env["VIRTUAL_ENV"] = str(venv)
        env.pop("PYTHONHOME", None)
    if front:
        env["PATH"] = os.pathsep.join([str(p) for p, _ in front] + [env.get("PATH", "")])
    return Toolchain(
        env,
        prepended=[(_show(cfg.root, p), why) for p, why in front],
        venv=_show(cfg.root, venv) if venv else "",
    )


def first_word(command: str) -> str:
    try:
        words = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        words = command.split()
    return words[0].strip("\"'") if words else ""


def _python_word(command: str) -> str:
    word = first_word(command)
    base = os.path.basename(word).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return word if base in PYTHONS else ""


def runner_module(command: str) -> str:
    """``pytest`` for ``python -m pytest ...``."""
    m = re.match(r"\s*\S+\s+-m\s+([\w.]+)", command)
    return m.group(1) if m and _python_word(command) else ""


def python_problem(command: str, env: dict[str, str]) -> str:
    """Why a leading ``python`` won't work here, or "" if it's fine (or not used)."""
    word = _python_word(command)
    if not word:
        return ""
    if os.path.dirname(word):
        exe = word if os.path.exists(word) else None
    else:
        exe = shutil.which(word, path=env.get("PATH", ""))
    if exe is None:
        return f"`{word}` was not found on PATH"
    try:
        proc = subprocess.run(
            [exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""  # let the real run report what's wrong
    version = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if version.startswith("2."):
        return f"`{word}` is Python {version} ({tilde(exe)})"
    return ""


def describe(command: str, env: dict[str, str]) -> str:
    """Which interpreter a leading ``python`` resolves to, for `sprint doctor`."""
    word = _python_word(command)
    if not word:
        return ""
    exe = shutil.which(word, path=env.get("PATH", "")) if not os.path.dirname(word) else word
    return f"`{word}` is {tilde(exe)}" if exe else ""


def missing_runner(command: str, tail: list[str]) -> str:
    """The runner module named in ``python -m <module>`` isn't installed."""
    module = runner_module(command)
    if not module:
        return ""
    needle = f"No module named {module}"
    return module if any(needle in line for line in tail) else ""


def is_environment_failure(runner: dict) -> bool:
    """The test command couldn't start, as opposed to a build or test failure."""
    if runner.get("environment"):
        return True
    return runner.get("exit_code") in (126, 127)
