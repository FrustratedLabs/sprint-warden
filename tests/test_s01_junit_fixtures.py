"""Phase 1: every stack's real (or faithfully reproduced) JUnit XML parses to the same scenario.

See tests/fixtures/junit/README.md for how each file was produced.
"""

from __future__ import annotations

import pytest

from sprintwarden.attribution import Attributor
from sprintwarden.junit import parse_files

P, F, S = "passed", "failed", "skipped"

EXPECTED: dict[str, list[tuple[str, str, str]]] = {
    "dotnet-junit.xml": [
        ("SprintDemo.Tests.AuthTests.S01_LoginSucceeds", P, "S01"),
        ("SprintDemo.Tests.AuthTests.S01_LogoutClearsSession", P, "S01"),
        ("SprintDemo.Tests.ExportTests.S03_ExportProducesPdf", P, "S03"),
        ("SprintDemo.Tests.HealthTests.HealthCheck", P, "legacy"),
        ("SprintDemo.Tests.InvoiceTests.S02_Crashes", F, "S02"),
        ("SprintDemo.Tests.InvoiceTests.S02_InvoicePdf", S, "S02"),
        ("SprintDemo.Tests.InvoiceTests.S02_InvoiceRounds", F, "S02"),
    ],
    "go-junit-report.xml": [
        ("example.com/sprintdemo/auth.Test_S01_LoginSucceeds", P, "S01"),
        ("example.com/sprintdemo/auth.Test_S01_LogoutClearsSession", P, "S01"),
        ("example.com/sprintdemo/export.TestExport", P, "legacy"),
        ("example.com/sprintdemo/export.TestExport/S03_export_produces_pdf", P, "S03"),
        ("example.com/sprintdemo/health.TestHealthCheck", P, "legacy"),
        ("example.com/sprintdemo/invoice.Test_S02_Crashes", F, "S02"),
        ("example.com/sprintdemo/invoice.Test_S02_InvoicePdf", S, "S02"),
        ("example.com/sprintdemo/invoice.Test_S02_InvoiceRounds", F, "S02"),
    ],
    "gradle-junit5.xml": [
        ("com.example.sprintdemo.AppTest.S01_loginSucceeds()", P, "S01"),
        ("com.example.sprintdemo.AppTest.S01_logoutClearsSession()", P, "S01"),
        ("com.example.sprintdemo.AppTest.S02_crashes()", F, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoicePdf()", S, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoiceRounds()", F, "S02"),
        ("com.example.sprintdemo.AppTest.[S03] export produces pdf", P, "S03"),
        ("com.example.sprintdemo.AppTest.healthCheck()", P, "legacy"),
    ],
    "jest-junit.xml": [
        ("S01_login_succeeds.S01_login_succeeds", P, "S01"),
        ("S01_logout_clears_session.S01_logout_clears_session", P, "S01"),
        ("S02_crashes.S02_crashes", F, "S02"),
        ("S02_invoice_pdf.S02_invoice_pdf", S, "S02"),
        ("S02_invoice_rounds.S02_invoice_rounds", F, "S02"),
        ("[S03] export produces pdf.[S03] export produces pdf", P, "S03"),
        ("health_check.health_check", P, "legacy"),
    ],
    "maven-surefire-flaky.xml": [
        ("com.example.sprintdemo.AppTest.S01_flakyRefresh", P, "S01"),
        ("com.example.sprintdemo.AppTest.S01_loginSucceeds", P, "S01"),
        ("com.example.sprintdemo.AppTest.S01_logoutClearsSession", P, "S01"),
        ("com.example.sprintdemo.AppTest.S02_crashes", F, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoicePdf", S, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoiceRounds", F, "S02"),
        ("com.example.sprintdemo.AppTest.S03_exportProducesPdf", P, "S03"),
        ("com.example.sprintdemo.AppTest.healthCheck", P, "legacy"),
    ],
    "maven-surefire.xml": [
        ("com.example.sprintdemo.AppTest.S01_loginSucceeds", P, "S01"),
        ("com.example.sprintdemo.AppTest.S01_logoutClearsSession", P, "S01"),
        ("com.example.sprintdemo.AppTest.S02_crashes", F, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoicePdf", S, "S02"),
        ("com.example.sprintdemo.AppTest.S02_invoiceRounds", F, "S02"),
        ("com.example.sprintdemo.AppTest.S03_exportProducesPdf", P, "S03"),
        ("com.example.sprintdemo.AppTest.healthCheck", P, "legacy"),
    ],
    "nextest.xml": [
        ("sprintdemo::auth.s01_login_succeeds", P, "S01"),
        ("sprintdemo::auth.s01_logout_clears_session", P, "S01"),
        ("sprintdemo::export.s03_export_produces_pdf", P, "S03"),
        ("sprintdemo::health.health_check", P, "legacy"),
        ("sprintdemo::invoice.s02_crashes", F, "S02"),
        ("sprintdemo::invoice.s02_invoice_rounds", F, "S02"),
    ],
    "pytest.xml": [
        ("tests.test_auth.test_S01_login_succeeds", P, "S01"),
        ("tests.test_auth.test_S01_logout_clears_session", P, "S01"),
        ("tests.test_export.test_S03_export[pdf]", P, "S03"),
        ("tests.test_health.test_health_check", P, "legacy"),
        ("tests.test_invoice.test_S02_crashes", F, "S02"),
        ("tests.test_invoice.test_S02_invoice_pdf", S, "S02"),
        ("tests.test_invoice.test_S02_invoice_rounds", F, "S02"),
    ],
    "swift-xunit.xml": [
        ("SprintDemoTests.AuthTests.test_S01_loginSucceeds", P, "S01"),
        ("SprintDemoTests.AuthTests.test_S01_logoutClearsSession", P, "S01"),
        ("SprintDemoTests.ExportTests.test_S03_exportProducesPdf", P, "S03"),
        ("SprintDemoTests.HealthTests.testHealthCheck", P, "legacy"),
        ("SprintDemoTests.InvoiceTests.test_S02_crashes", F, "S02"),
        ("SprintDemoTests.InvoiceTests.test_S02_invoicePdf", P, "S02"),
        ("SprintDemoTests.InvoiceTests.test_S02_invoiceRounds", F, "S02"),
    ],
    "vitest.xml": [
        ("tests/auth.test.ts.S01_login_succeeds", P, "S01"),
        ("tests/auth.test.ts.S01_logout_clears_session", P, "S01"),
        ("tests/export.test.ts.[S03] export > produces pdf", P, "S03"),
        ("tests/health.test.ts.health_check", P, "legacy"),
        ("tests/invoice.test.ts.S02_crashes", F, "S02"),
        ("tests/invoice.test.ts.S02_invoice_pdf", S, "S02"),
        ("tests/invoice.test.ts.S02_invoice_rounds", F, "S02"),
    ],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_S01_fixture_parses_to_the_scenario(fixtures, name):
    res = parse_files([fixtures / "junit" / name])
    assert not res.errors and not res.ignored
    attr = Attributor()
    got = sorted((t.id, t.outcome, attr.sprint_of(t.classname, t.name)) for t in res.tests.values())
    assert got == sorted(EXPECTED[name])


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_S01_failures_carry_a_useful_message(fixtures, name):
    res = parse_files([fixtures / "junit" / name])
    rounds = [t for t in res.tests.values() if "rounds" in t.id.lower() and t.outcome == F]
    if name == "swift-xunit.xml":
        pytest.skip("SwiftPM writes the literal message 'failure' with an empty body")
    assert rounds, name
    msg = rounds[0].message
    if name == "nextest.xml":
        assert "panicked at tests/invoice.rs" in msg
    else:
        assert "expected" in msg.lower() or "assert" in msg.lower(), msg


def test_S01_all_fixtures_merge_without_collisions(fixtures):
    files = sorted((fixtures / "junit").glob("*.xml"))
    res = parse_files(files)
    assert len(res.files) == len(EXPECTED)
    # maven-surefire.xml and maven-surefire-flaky.xml share 7 ids
    assert res.duplicates == 7
    assert res.tests["com.example.sprintdemo.AppTest.S01_flakyRefresh"].flaky


def test_S01_known_stack_quirks_are_documented(fixtures):
    """Swift reports XCTSkip as a pass, nextest omits #[ignore] tests: the ratchet
    still catches the latter as 'missing'. Keep README/ADDING_A_STACK in sync."""
    swift = parse_files([fixtures / "junit" / "swift-xunit.xml"]).tests
    assert swift["SprintDemoTests.InvoiceTests.test_S02_invoicePdf"].outcome == P
    nextest = parse_files([fixtures / "junit" / "nextest.xml"]).tests
    assert not any("invoice_pdf" in t for t in nextest)
