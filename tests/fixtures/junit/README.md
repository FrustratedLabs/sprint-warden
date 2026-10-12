# JUnit XML fixtures

Every file reports the same 7-test scenario (S01 login/logout pass, S02 invoice rounding fails with `expected 10 but was 11`, S02 invoice pdf skipped `not ready`, legacy health check passes, S02 crash `boom`, S03 export produces pdf passes), produced by a tiny synthetic project per stack.

- `pytest.xml`: pytest 9.1.1 (CPython 3.11.17), **real**: `pytest --junitxml=pytest.xml`
- `vitest.xml`: vitest 5.0.3 (Node 22.23.1), **real**: `npx vitest run --reporter=junit --outputFile=vitest.xml`
- `jest-junit.xml`: jest 30.5.2 + jest-junit 17.0.0 (default options), **real**: `JEST_JUNIT_OUTPUT_DIR=. npx jest --ci --reporters=default --reporters=jest-junit` (default `junit.xml`, renamed)
- `go-junit-report.xml`: go-junit-report v2.1.0 (go1.24.6), **real**: `go test ./... -v 2>&1 | go-junit-report > go-junit-report.xml`
- `swift-xunit.xml`: SwiftPM 6.2.4 XCTest xUnit format, **hand-written** (XCTest unavailable on the generating machine; reproduces `XUnitGenerator` in SwiftPM `swift-6.2.4-RELEASE`): `swift test --parallel --xunit-output swift-xunit.xml`
- `gradle-junit5.xml`: Gradle 8.14.6, JUnit Jupiter 5.14.4, Java 17.0.15, **real**: `gradle test` (copy of `build/test-results/test/TEST-com.example.sprintdemo.AppTest.xml`)
- `maven-surefire.xml`: Maven 3.9.16, maven-surefire-plugin 3.6.0, JUnit Jupiter 5.14.4, Java 17.0.15, **real**: `mvn test` (copy of `target/surefire-reports/TEST-com.example.sprintdemo.AppTest.xml`)
- `maven-surefire-flaky.xml`: same toolchain plus an extra `S01_flakyRefresh` test that fails only on its first attempt, **real**: `mvn -Dsurefire.rerunFailingTestsCount=2 clean test`
- `nextest.xml`: cargo-nextest 0.9.148 (rustc 1.96.0), **real**: `cargo nextest run --profile ci` with `.config/nextest.toml` = `[profile.ci] fail-fast = false` + `[profile.ci.junit] path = "junit.xml"` (copy of `target/nextest/ci/junit.xml`)
- `dotnet-junit.xml`: JunitXml.TestLogger 8.0.0 with xunit 2.9.3 + xunit.runner.visualstudio 3.1.4 on .NET 8, **hand-written** (dotnet unavailable on the generating machine; reproduces `JunitXmlSerializer` in spekt/testlogger `v8.0.0`): `dotnet test --logger "junit;LogFilePath=dotnet-junit.xml"`

Scrubbing applied to the real files (otherwise byte-for-byte tool output): `hostname` attributes set to `localhost`, absolute project paths rewritten to `/home/dev/project`, Homebrew GOROOT rewritten to `/usr/local/go`, and surefire `<properties>` trimmed to `java.specification.version`, `file.encoding` and `java.version`.

Timestamp offsets were normalized to `+00:00` (the generating machine's local offset is not part of the format).
