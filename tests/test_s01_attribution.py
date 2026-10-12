from __future__ import annotations

import pytest

from sprintwarden.attribution import (
    LEGACY,
    Attributor,
    TestIndex,
    TestMatcher,
    evaluate_ac,
    normalize_sprint_id,
    sort_sprint_keys,
    sprint_number,
)
from sprintwarden.util import SprintError


@pytest.mark.parametrize(
    ("classname", "name", "expected"),
    [
        # JUnit / Gradle / Maven method names
        ("com.acme.ReportExportTest", "S03_exportsPdf()", "S03"),
        ("com.acme.ReportExportTest", "S03_exportsPdf", "S03"),
        # JUnit5 display names and vitest/jest describe blocks
        ("com.acme.ReportExportTest", "[S03] export produces pdf", "S03"),
        ("src/report.test.ts", "[S03] export > produces pdf", "S03"),
        ("export", "S03: produces pdf", "S03"),
        ("export", "S03 - produces pdf", "S03"),
        # pytest / XCTest / Go need a test prefix; underscores are fine before the id
        ("tests.test_reports", "test_S03_exports_pdf", "S03"),
        ("tests.test_reports", "test_S03_export[pdf]", "S03"),
        ("MyTests.ReportTests", "test_S03_exportsPdf", "S03"),
        ("github.com/acme/report", "Test_S03_ExportsPdf", "S03"),
        ("github.com/acme/report", "TestExport/S03_export_produces_pdf", "S03"),
        # Rust (lowercase), dotnet
        ("acme", "tests::s03_exports_pdf", "S03"),
        ("Acme.Tests.ReportTests", "S03_ExportsPdf", "S03"),
        # three-digit sprints for long-running projects
        ("x.Y", "S100_bigProject", "S100"),
        ("x.Y", "S007_paddedId", "S07"),
        # end of string
        ("x.Y", "regression for S12", "S12"),
        # class-level attribution when the method has no id
        ("com.acme.S04_BillingTest", "roundsToCents", "S04"),
        ("tests.s05_billing", "test_rounds", "S05"),
        # method id wins over class id
        ("com.acme.S04_BillingTest", "S05_newRounding", "S05"),
        # legacy: no id, or id glued to other letters/digits
        ("com.acme.AuthTest", "lockoutAfter5Attempts", LEGACY),
        ("com.acme.AuthTest", "BS03_notASprint", LEGACY),
        ("com.acme.AuthTest", "S03exportsPdf", LEGACY),
        ("com.acme.AuthTest", "uses S3 bucket", LEGACY),
        ("com.acme.AuthTest", "class1S03_x", LEGACY),
        ("", "", LEGACY),
    ],
)
def test_S01_default_pattern_attributes_every_stack_naming_style(classname, name, expected):
    assert Attributor().sprint_of(classname, name) == expected


def test_S01_custom_pattern_with_group():
    attr = Attributor(r"SPRINT-(\d+)")
    assert attr.sprint_of("a", "SPRINT-7 does x") == "S07"
    assert attr.sprint_of("a", "S07_does_x") == LEGACY


def test_S01_pattern_without_group_is_rejected():
    with pytest.raises(SprintError):
        Attributor(r"S\d+")


def test_S01_invalid_pattern_is_rejected():
    with pytest.raises(SprintError):
        Attributor(r"S(\d+")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("S03", "S03"), ("s3", "S03"), ("S003", "S03"), (" S100 ", "S100"), ("S0", "S00")],
)
def test_S01_normalize_sprint_id(raw, expected):
    assert normalize_sprint_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "X03", "S", "S3a", "03"])
def test_S01_normalize_sprint_id_rejects_garbage(raw):
    with pytest.raises(SprintError):
        normalize_sprint_id(raw)


def test_S01_sprints_sort_numerically_with_legacy_first():
    assert sort_sprint_keys(["S10", "S100", "legacy", "S02", "S09"]) == [
        "legacy",
        "S02",
        "S09",
        "S10",
        "S100",
    ]
    assert sprint_number("legacy") == -1


def test_S01_matcher_substring_and_regex():
    assert TestMatcher("S03_exportsPdf").matches("com.acme.ReportTest.S03_exportsPdf()")
    assert not TestMatcher("S03_exportsPdf").matches("com.acme.ReportTest.S03_exportsCsv()")
    rx = TestMatcher("/S03_.*Placeholder.*/")
    assert rx.matches("ReportTest.S03_emptyMonthPlaceholderPage")
    assert not rx.matches("ReportTest.S02_emptyMonthPlaceholderPage")
    assert TestMatcher("/s03_export/i").matches("x.S03_EXPORT")


def test_S01_matcher_rejects_bad_regex_and_empty():
    with pytest.raises(SprintError):
        TestMatcher("/S03_(/")
    with pytest.raises(SprintError):
        TestMatcher("")


IDS = [
    "com.acme.ReportTest.S03_exportsPdf()",
    "com.acme.ReportTest.S03_exportsCsv()",
    "com.acme.ReportTest.S03_emptyMonthPlaceholder()",
    "com.acme.AuthTest.S01_login()",
    "tests.test_x.test_S03_export[pdf]",
]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("S03_exports", IDS[:2]),
        ("ReportTest.S03", IDS[:3]),
        ("/S03_.*Placeholder.*/", [IDS[2]]),
        ("/^com\\.acme\\.AuthTest/", [IDS[3]]),
        ("/\\)$/", IDS[:4]),
        ("/\\[pdf\\]$/", [IDS[4]]),
        ("/\\Atests\\./", [IDS[4]]),
        ("nothing-matches", []),
        # a regex that could span two IDs in the joined index must not
        ("/exportsPdf\\(\\)\\s+com/", []),
        ("/.*/", IDS),
    ],
)
def test_S01_index_find_matches_per_id_semantics(spec, expected):
    index = TestIndex(IDS)
    m = TestMatcher(spec)
    assert index.find(m) == expected
    assert index.find(m) == [t for t in IDS if m.matches(t)]


def test_S01_index_handles_overlapping_and_repeated_hits():
    ids = ["a.aaa", "b.aaaa", "c.b"]
    index = TestIndex(ids)
    assert index.find(TestMatcher("aa")) == ["a.aaa", "b.aaaa"]
    assert index.find(TestMatcher("/a{2}/")) == ["a.aaa", "b.aaaa"]
    assert TestIndex([]).find(TestMatcher("x")) == []


def test_S01_ac_satisfied_failing_and_no_tests():
    outcomes = {
        "R.S03_exportsPdf": "passed",
        "R.S03_placeholderA": "passed",
        "R.S03_placeholderB": "failed",
        "R.S03_skipped": "skipped",
    }
    ok = evaluate_ac("S03", "AC1", "pdf", ["S03_exportsPdf"], outcomes)
    assert ok.satisfied and ok.state == "satisfied"
    assert ok.tests == [{"id": "R.S03_exportsPdf", "outcome": "passed"}]

    failing = evaluate_ac("S03", "AC2", "placeholder", ["/S03_placeholder.*/"], outcomes)
    assert failing.state == "failing" and not failing.satisfied
    assert [t["outcome"] for t in failing.tests] == ["passed", "failed"]

    skipped = evaluate_ac("S03", "AC3", "skip", ["S03_skipped"], outcomes)
    assert skipped.state == "failing", "a skipped test does not satisfy an AC"

    none = evaluate_ac("S03", "AC4", "nothing", ["S03_missing"], outcomes)
    assert none.state == "no-tests"

    empty = evaluate_ac("S03", "AC5", "no patterns", [], outcomes)
    assert empty.state == "no-tests"


def test_S01_ac_union_of_patterns_is_deduplicated():
    outcomes = {"R.S03_a": "passed", "R.S03_b": "passed"}
    res = evaluate_ac("S03", "AC1", "", ["S03_a", "/S03_[ab]/"], outcomes)
    assert [t["id"] for t in res.tests] == ["R.S03_a", "R.S03_b"]
    data = res.to_json(test_cap=1)
    assert data["tests_truncated"] == 1 and len(data["tests"]) == 1


def test_S01_index_scales_to_large_suites():
    ids = [f"pkg.Class{i // 50}.S{(i % 40) + 1:02d}_case{i}" for i in range(50_000)]
    index = TestIndex(ids)
    hits = index.find(TestMatcher("S07_case"))
    assert len(hits) == 1250
    assert index.find(TestMatcher("/Class999\\.S10_/")) == [t for t in ids if "Class999.S10_" in t]
