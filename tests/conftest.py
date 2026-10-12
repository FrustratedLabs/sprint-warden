from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.sprintwarden; never inherit an agent identity."""
    home = tmp_path_factory.mktemp("sprint-home")
    monkeypatch.setenv("SPRINT_HOME", str(home))
    monkeypatch.setenv("SPRINT_AGENT", "human")
    monkeypatch.delenv("SPRINT_SKIP", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    yield home


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def writer():
    return write


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
