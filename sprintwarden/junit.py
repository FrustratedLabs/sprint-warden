"""JUnit XML parsing: the only contract sprintwarden has with test runners.

Accepts a ``<testsuites>`` or bare ``<testsuite>`` root, with nested suites.
Files are parsed incrementally (``iterparse``) so suites with very large
``<system-out>`` blocks don't need to fit in memory at once.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
_RANK = {FAILED: 2, PASSED: 1, SKIPPED: 0}

MESSAGE_LIMIT = 500

_SKIP_STATUSES = {"skipped", "skip", "disabled", "ignored", "notrun", "not_run", "pending"}


class NotJUnitError(Exception):
    """The file is XML but not a JUnit report (e.g. testng-results.xml)."""


class JUnitParseError(Exception):
    """The file is malformed (truncated, invalid characters...)."""


@dataclass(slots=True)
class TestCase:
    id: str
    classname: str
    name: str
    outcome: str
    message: str = ""
    time: float = 0.0
    file: str = ""
    flaky: bool = False
    count: int = 1
    sprint: str = ""

    __test__ = False  # not a pytest class


@dataclass
class ParseResult:
    tests: dict[str, TestCase] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    ignored: list[tuple[str, str]] = field(default_factory=list)
    duplicates: int = 0

    def outcomes(self) -> dict[str, str]:
        return {t.id: t.outcome for t in self.tests.values()}


def normalize(text: str | None) -> str:
    return " ".join((text or "").split())


def test_id(classname: str, name: str) -> str:
    return f"{classname}.{name}" if classname else name


test_id.__test__ = False  # type: ignore[attr-defined]


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


_GENERIC_MESSAGES = {"", "failed", "failure", "error", "test failure", "skipped", "fail"}


def _message(elem: ET.Element) -> str:
    """One-line message: the ``message`` attribute, or the body when that is generic."""
    attr = normalize(elem.get("message"))
    if attr.lower() in _GENERIC_MESSAGES:
        attr = ""
    msg = attr or normalize(elem.text) or normalize(elem.get("type"))
    if len(msg) > MESSAGE_LIMIT:
        msg = msg[: MESSAGE_LIMIT - 1] + "…"
    return msg


def _case(elem: ET.Element, suites: list[str], file: str) -> TestCase:
    classname = normalize(elem.get("classname"))
    if not classname:
        classname = next((s for s in reversed(suites) if s), "")
    name = normalize(elem.get("name"))
    outcome = PASSED
    message = ""
    flaky = False
    skip_message = ""
    for child in elem:
        tag = _local(child.tag)
        if tag in ("failure", "error"):
            if outcome != FAILED:
                outcome = FAILED
                message = _message(child)
        elif tag == "skipped":
            skip_message = _message(child)
            if outcome == PASSED:
                outcome = SKIPPED
        elif tag in ("flakyFailure", "flakyError"):
            flaky = True
    status = (elem.get("status") or elem.get("result") or "").strip().lower()
    if outcome == PASSED and status in _SKIP_STATUSES:
        outcome = SKIPPED
    if outcome == SKIPPED:
        message = skip_message
    try:
        seconds = float(elem.get("time") or 0)
    except ValueError:
        seconds = 0.0
    return TestCase(
        id=test_id(classname, name),
        classname=classname,
        name=name,
        outcome=outcome,
        message=message,
        time=seconds,
        file=file,
        flaky=flaky,
    )


def _iter_cases(source: str | io.BytesIO, file: str) -> list[TestCase]:
    cases: list[TestCase] = []
    suites: list[str] = []
    depth_case = 0
    root_checked = False
    for event, elem in ET.iterparse(source, events=("start", "end")):
        tag = _local(elem.tag)
        if event == "start":
            if not root_checked:
                root_checked = True
                if tag not in ("testsuites", "testsuite"):
                    raise NotJUnitError(f"root element is <{tag}>, not <testsuites>/<testsuite>")
            if tag == "testsuite":
                suites.append(normalize(elem.get("name")))
            elif tag == "testcase":
                depth_case += 1
            continue
        if tag == "testcase":
            depth_case -= 1
            cases.append(_case(elem, suites, file))
            elem.clear()
        elif tag == "testsuite":
            if suites:
                suites.pop()
            elem.clear()
        elif tag in ("system-out", "system-err", "properties") and depth_case == 0:
            elem.clear()
    if not root_checked:
        raise JUnitParseError("empty document")
    return cases


# XML 1.0 forbids most control characters, but some runners emit them anyway
# (ANSI colour codes in captured output). Strip them and retry once.
_BAD_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_REFS = re.compile(
    rb"&#(?:x0*(?:[0-8bcef]|1[0-9a-f])|0*(?:[0-8]|1[124-9]|2[0-9]|3[01]));", re.I
)


def parse_file(path: str | Path) -> list[TestCase]:
    path = str(path)
    try:
        return _iter_cases(path, path)
    except NotJUnitError:
        raise
    except ET.ParseError as first:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise JUnitParseError(str(exc)) from exc
        cleaned = _BAD_REFS.sub(b"", _BAD_CHARS.sub(b"", data))
        if cleaned == data:
            raise JUnitParseError(str(first)) from first
        try:
            return _iter_cases(io.BytesIO(cleaned), path)
        except ET.ParseError as exc:
            raise JUnitParseError(str(exc)) from exc
    except OSError as exc:
        raise JUnitParseError(str(exc)) from exc


def merge(result: ParseResult, cases: Iterable[TestCase]) -> None:
    """Merge cases by identity. A duplicate counts as failed if any instance failed."""
    tests = result.tests
    for case in cases:
        existing = tests.get(case.id)
        if existing is None:
            tests[case.id] = case
            continue
        result.duplicates += 1
        existing.count += 1
        existing.flaky = existing.flaky or case.flaky
        existing.time = max(existing.time, case.time)
        if _RANK[case.outcome] > _RANK[existing.outcome]:
            existing.outcome = case.outcome
            existing.message = case.message
            existing.file = case.file


def parse_files(paths: Iterable[str | Path]) -> ParseResult:
    result = ParseResult()
    for p in paths:
        p = str(p)
        try:
            cases = parse_file(p)
        except NotJUnitError as exc:
            result.ignored.append((p, str(exc)))
            continue
        except JUnitParseError as exc:
            result.errors.append((p, str(exc)))
            continue
        result.files.append(p)
        merge(result, cases)
    return result
