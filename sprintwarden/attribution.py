"""Sprint attribution by test name, and acceptance-criteria matching.

A test belongs to sprint S03 when its name (or, failing that, its classname)
contains the sprint ID, e.g. ``S03_exportsPdf``, ``test_S03_exports_pdf`` or
``describe("[S03] export")``. Tests with no sprint ID go in the ``legacy``
bucket; they still count for regressions and the ratchet.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sprintwarden.util import SprintError

LEGACY = "legacy"

# The sprint ID must not be glued to a preceding letter or digit (so "BS03" and
# "class1S03" don't match), but an underscore is fine: pytest, XCTest and Go
# need a `test_`/`Test_` prefix. It must end at a separator, never mid-word.
DEFAULT_ID_PATTERN = r"(?i)(?<![A-Za-z0-9])S(\d{2,})(?=[_\]\s:.()\[/-]|$)"

_SPRINT_ID_RE = re.compile(r"(?i)^\s*s(\d+)\s*$")


def normalize_sprint_id(value: str) -> str:
    """``"s3"``, ``"S03"`` and ``"S003"`` all become ``"S03"``; ``"S100"`` stays."""
    m = _SPRINT_ID_RE.match(str(value))
    if not m:
        raise SprintError(f"invalid sprint id {value!r} (expected S01, S02, ...)")
    return format_sprint_id(int(m.group(1)))


def format_sprint_id(number: int) -> str:
    return f"S{number:02d}"


def sprint_number(sprint_id: str) -> int:
    """Sort key: legacy first, then sprints numerically (S99 < S100)."""
    if sprint_id == LEGACY:
        return -1
    m = _SPRINT_ID_RE.match(sprint_id)
    return int(m.group(1)) if m else -1


def sort_sprint_keys(keys: Iterable[str]) -> list[str]:
    return sorted(keys, key=lambda k: (sprint_number(k), k))


class Attributor:
    def __init__(self, pattern: str = DEFAULT_ID_PATTERN) -> None:
        try:
            self.regex = re.compile(pattern)
        except re.error as exc:
            raise SprintError(f"invalid sprint id_pattern: {exc}") from exc
        if self.regex.groups < 1:
            raise SprintError("sprint id_pattern needs a capture group for the sprint number")
        self._cache: dict[tuple[str, str], str] = {}

    def sprint_of(self, classname: str, name: str) -> str:
        key = (classname, name)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._match(name) or self._match(classname) or LEGACY
            self._cache[key] = hit
        return hit

    def _match(self, text: str) -> str | None:
        if not text:
            return None
        m = self.regex.search(text)
        if not m:
            return None
        try:
            return format_sprint_id(int(m.group(1)))
        except (TypeError, ValueError):
            return None


class TestMatcher:
    """An AC ``tests`` entry: a plain substring, or ``/regex/flags`` on the full test ID."""

    __test__ = False  # not a pytest class

    _RX = re.compile(r"^/(.+)/([imsx]*)$", re.S)

    def __init__(self, spec: str) -> None:
        self.spec = spec
        m = self._RX.match(spec)
        self.regex: re.Pattern[str] | None = None
        if m:
            flags = 0
            for ch in m.group(2):
                flags |= {"i": re.I, "m": re.M, "s": re.S, "x": re.X}[ch]
            try:
                self.regex = re.compile(m.group(1), flags)
            except re.error as exc:
                raise SprintError(f"invalid AC test regex {spec!r}: {exc}") from exc
        elif not spec:
            raise SprintError("empty AC test pattern")

    def matches(self, test_id: str) -> bool:
        if self.regex is not None:
            return self.regex.search(test_id) is not None
        return self.spec in test_id


class TestIndex:
    """Fast lookup of which test IDs match an AC pattern.

    Large projects have tens of thousands of tests and hundreds of ACs; joining
    the IDs into one string lets ``str.find``/``re.finditer`` scan in C instead
    of looping over every test in Python for every AC.
    """

    __test__ = False

    def __init__(self, test_ids: Iterable[str]) -> None:
        self.ids = [t.replace("\n", " ") for t in test_ids]
        self._starts: list[int] = []
        pos = 0
        for t in self.ids:
            self._starts.append(pos)
            pos += len(t) + 1
        self._blob = "\n".join(self.ids)

    def _line_at(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset) - 1

    def find(self, matcher: TestMatcher) -> list[str]:
        """Return matching test IDs in index order.

        Each candidate found in the blob is re-verified against its own ID, and
        the scan resumes at the next ID, so a match that spans two IDs can
        neither produce a false hit nor hide a real one.
        """
        if not self.ids:
            return []
        hits: list[int] = []
        if matcher.regex is None:
            needle = matcher.spec

            def search(pos: int) -> int:
                return self._blob.find(needle, pos)

            def verify(test_id: str) -> bool:
                return needle in test_id
        else:
            single = matcher.regex
            if re.search(r"\\[AZz]", single.pattern):
                # String anchors only make sense per ID; take the simple path.
                return [t for t in self.ids if single.search(t)]
            # ^ and $ mean "start/end of the test ID"; the blob has one ID per line.
            scan = re.compile(single.pattern, single.flags | re.M)

            def search(pos: int) -> int:
                m = scan.search(self._blob, pos)
                return m.start() if m else -1

            def verify(test_id: str) -> bool:
                return single.search(test_id) is not None

        pos = 0
        while pos <= len(self._blob):
            i = search(pos)
            if i < 0:
                break
            line = self._line_at(i)
            if verify(self.ids[line]):
                hits.append(line)
            pos = self._starts[line] + len(self.ids[line]) + 1
        return [self.ids[i] for i in hits]


@dataclass
class ACResult:
    sprint: str
    id: str
    desc: str
    state: str  # "satisfied" | "failing" | "no-tests"
    tests: list[dict[str, str]]

    @property
    def satisfied(self) -> bool:
        return self.state == "satisfied"

    def to_json(self, test_cap: int | None = None) -> dict:
        tests = self.tests if test_cap is None else self.tests[:test_cap]
        data = {
            "sprint": self.sprint,
            "id": self.id,
            "desc": self.desc,
            "satisfied": self.satisfied,
            "state": self.state,
            "tests": tests,
        }
        if test_cap is not None and len(self.tests) > test_cap:
            data["tests_truncated"] = len(self.tests) - test_cap
        return data


def evaluate_ac(
    sprint: str,
    ac_id: str,
    desc: str,
    patterns: list[str],
    outcomes: Mapping[str, str],
    index: TestIndex | None = None,
) -> ACResult:
    """An AC is satisfied when >=1 test matches and every matching test passed."""
    index = index or TestIndex(outcomes.keys())
    matched: dict[str, None] = {}
    for pattern in patterns:
        for test_id in index.find(TestMatcher(pattern)):
            matched[test_id] = None
    tests = [{"id": t, "outcome": outcomes.get(t, "missing")} for t in matched]
    if not tests:
        state = "no-tests"
    elif all(t["outcome"] == "passed" for t in tests):
        state = "satisfied"
    else:
        state = "failing"
    return ACResult(sprint=sprint, id=ac_id, desc=desc, state=state, tests=tests)
