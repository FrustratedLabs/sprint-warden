from __future__ import annotations

from pathlib import Path

import pytest

from sprintwarden.junit import (
    FAILED,
    MESSAGE_LIMIT,
    PASSED,
    SKIPPED,
    JUnitParseError,
    NotJUnitError,
    parse_file,
    parse_files,
)


def xml(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_S01_bare_testsuite_root(tmp_path):
    p = xml(
        tmp_path,
        "a.xml",
        """<?xml version="1.0"?>
<testsuite name="com.acme.AuthTest" tests="3">
  <testcase classname="com.acme.AuthTest" name="S01_login" time="0.01"/>
  <testcase classname="com.acme.AuthTest" name="S01_lockout" time="0.02">
    <failure message="expected 423 but was 200" type="AssertionError">stack</failure>
  </testcase>
  <testcase classname="com.acme.AuthTest" name="S02_sso"><skipped message="not ready"/></testcase>
</testsuite>""",
    )
    cases = {c.id: c for c in parse_file(p)}
    assert list(cases) == [
        "com.acme.AuthTest.S01_login",
        "com.acme.AuthTest.S01_lockout",
        "com.acme.AuthTest.S02_sso",
    ]
    assert cases["com.acme.AuthTest.S01_login"].outcome == PASSED
    assert cases["com.acme.AuthTest.S01_login"].time == pytest.approx(0.01)
    lock = cases["com.acme.AuthTest.S01_lockout"]
    assert lock.outcome == FAILED and lock.message == "expected 423 but was 200"
    sso = cases["com.acme.AuthTest.S02_sso"]
    assert sso.outcome == SKIPPED and sso.message == "not ready"


def test_S01_testsuites_root_with_nested_suites_and_missing_classname(tmp_path):
    p = xml(
        tmp_path,
        "nested.xml",
        """<testsuites name="all">
  <testsuite name="outer">
    <testsuite name="inner">
      <testcase name="S01_a"/>
    </testsuite>
    <testcase name="S01_b"/>
    <testsuite name="">
      <testcase name="S01_c"/>
    </testsuite>
  </testsuite>
  <testsuite name="second"><testcase classname="Explicit" name="S01_d"/></testsuite>
</testsuites>""",
    )
    ids = [c.id for c in parse_file(p)]
    assert ids == ["inner.S01_a", "outer.S01_b", "outer.S01_c", "Explicit.S01_d"]


def test_S01_error_counts_as_failed_and_failure_beats_skip(tmp_path):
    p = xml(
        tmp_path,
        "e.xml",
        """<testsuite name="s">
  <testcase classname="C" name="crashes"><error message="RuntimeError: boom" type="RuntimeError"/></testcase>
  <testcase classname="C" name="both"><skipped/><failure message="real failure"/></testcase>
</testsuite>""",
    )
    cases = {c.name: c for c in parse_file(p)}
    assert cases["crashes"].outcome == FAILED
    assert cases["crashes"].message == "RuntimeError: boom"
    assert cases["both"].outcome == FAILED and cases["both"].message == "real failure"


def test_S01_generic_message_falls_back_to_body(tmp_path):
    p = xml(
        tmp_path,
        "g.xml",
        """<testsuite name="pkg">
  <testcase classname="pkg" name="Test_S02_Rounds"><failure message="Failed" type="">    rounding_test.go:12: expected 10 but was 11
  </failure></testcase>
  <testcase classname="pkg" name="T"><failure>   multi
  line    body </failure></testcase>
  <testcase classname="pkg" name="U"><failure type="AssertionError"/></testcase>
</testsuite>""",
    )
    cases = {c.name: c for c in parse_file(p)}
    assert cases["Test_S02_Rounds"].message == "rounding_test.go:12: expected 10 but was 11"
    assert cases["T"].message == "multi line body"
    assert cases["U"].message == "AssertionError"


def test_S01_message_is_capped(tmp_path):
    p = xml(
        tmp_path,
        "m.xml",
        f'<testsuite name="s"><testcase classname="C" name="x"><failure message="{"y" * 2000}"/></testcase></testsuite>',
    )
    (case,) = parse_file(p)
    assert len(case.message) == MESSAGE_LIMIT and case.message.endswith("…")


def test_S01_identity_is_whitespace_normalized(tmp_path):
    p = xml(
        tmp_path,
        "w.xml",
        """<testsuite name="s"><testcase classname="  a.B  " name="S01  does
        thing "/></testsuite>""",
    )
    (case,) = parse_file(p)
    assert case.id == "a.B.S01 does thing"


def test_S01_status_attribute_marks_skips(tmp_path):
    p = xml(
        tmp_path,
        "st.xml",
        """<testsuite name="s">
<testcase classname="C" name="a" status="notrun"/>
<testcase classname="C" name="b" status="run"/>
<testcase classname="C" name="c" result="skipped"/>
</testsuite>""",
    )
    assert [c.outcome for c in parse_file(p)] == [SKIPPED, PASSED, SKIPPED]


def test_S01_surefire_flaky_reruns(tmp_path):
    p = xml(
        tmp_path,
        "f.xml",
        """<testsuite name="T">
<testcase classname="T" name="flakyThenPasses"><flakyFailure message="first try"/></testcase>
<testcase classname="T" name="alwaysFails"><failure message="nope"/><rerunFailure message="nope"/></testcase>
</testsuite>""",
    )
    cases = {c.name: c for c in parse_file(p)}
    assert cases["flakyThenPasses"].outcome == PASSED and cases["flakyThenPasses"].flaky
    assert cases["alwaysFails"].outcome == FAILED


def test_S01_namespaced_elements(tmp_path):
    p = xml(
        tmp_path,
        "ns.xml",
        """<testsuites xmlns="urn:example"><testsuite name="s">
<testcase classname="C" name="a"><skipped/></testcase></testsuite></testsuites>""",
    )
    (case,) = parse_file(p)
    assert case.outcome == SKIPPED


def test_S01_merge_duplicates_failed_wins(tmp_path):
    a = xml(
        tmp_path,
        "a.xml",
        """<testsuite name="s">
<testcase classname="C" name="dup"/>
<testcase classname="C" name="dup"><failure message="second run failed"/></testcase>
<testcase classname="C" name="skipThenPass"><skipped/></testcase>
</testsuite>""",
    )
    b = xml(
        tmp_path,
        "b.xml",
        """<testsuite name="s">
<testcase classname="C" name="dup"/>
<testcase classname="C" name="skipThenPass"/>
<testcase classname="D" name="other"/>
</testsuite>""",
    )
    res = parse_files([a, b])
    assert list(res.tests) == ["C.dup", "C.skipThenPass", "D.other"]
    dup = res.tests["C.dup"]
    assert dup.outcome == FAILED and dup.count == 3 and dup.message == "second run failed"
    assert res.tests["C.skipThenPass"].outcome == PASSED
    assert res.duplicates == 3
    assert res.files == [str(a), str(b)]


def test_S01_non_junit_xml_is_ignored_not_fatal(tmp_path):
    p = xml(tmp_path, "testng-results.xml", "<testng-results><suite/></testng-results>")
    with pytest.raises(NotJUnitError):
        parse_file(p)
    res = parse_files([p])
    assert res.ignored and not res.errors and not res.tests


def test_S01_truncated_xml_is_an_error(tmp_path):
    p = xml(tmp_path, "t.xml", '<testsuite name="s"><testcase classname="C" name="a">')
    with pytest.raises(JUnitParseError):
        parse_file(p)
    res = parse_files([p])
    assert res.errors and res.errors[0][0] == str(p)


def test_S01_empty_file_is_an_error(tmp_path):
    p = xml(tmp_path, "empty.xml", "")
    res = parse_files([p])
    assert res.errors


def test_S01_missing_file_is_an_error(tmp_path):
    res = parse_files([tmp_path / "nope.xml"])
    assert res.errors


def test_S01_control_characters_are_tolerated(tmp_path):
    p = tmp_path / "ctrl.xml"
    p.write_bytes(
        b'<testsuite name="s"><testcase classname="C" name="colour">'
        b'<failure message="bad \x1b[31mred\x1b[0m">x&#27;y</failure></testcase></testsuite>'
    )
    (case,) = parse_file(p)
    assert case.outcome == FAILED
    assert "red" in case.message


def test_S01_suite_with_zero_tests(tmp_path):
    p = xml(tmp_path, "z.xml", '<testsuites><testsuite name="s" tests="0"/></testsuites>')
    assert parse_file(p) == []


def test_S01_large_file_streams(tmp_path):
    p = tmp_path / "big.xml"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("<testsuites>")
        for s in range(200):
            fh.write(f'<testsuite name="pkg.Suite{s}">')
            for i in range(100):
                fh.write(f'<testcase classname="pkg.Suite{s}" name="S01_t{i}">')
                fh.write("<system-out>" + ("log line\n" * 20) + "</system-out></testcase>")
            fh.write(
                "<system-out>suite log</system-out><properties><property name='a' value='b'/></properties>"
            )
            fh.write("</testsuite>")
        fh.write("</testsuites>")
    res = parse_files([p])
    assert len(res.tests) == 20_000
    assert all(t.outcome == PASSED for t in res.tests.values())
