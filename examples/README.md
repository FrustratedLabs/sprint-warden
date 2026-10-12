# Examples

Tiny real projects, each with two sprints (S01 closed, S02 active) and a scripted
"agent breaks S01 while working on S02" branch.

| example | stack | what the regression does |
|---|---|---|
| [pytest-invoices](pytest-invoices) | pytest | float maths breaks half-up rounding; the cheat branch also deletes the S01 test |
| [vitest-cart](vitest-cart) | Vitest | a refactor drops the line quantity |
| [go-shapes](go-shapes) | Go + go-junit-report | the circle-area formula is swapped |
| [gradle-library](gradle-library) | Gradle + JUnit 5 | the Fahrenheit conversion is "optimised" |

```sh
sh examples/run-all.sh            # or: pwsh examples/run-all.ps1
```

```
[PASS] pytest
         init: baseline of 7 tests
         main: PASS, 2/2 S02 ACs satisfied
         s01-regression: FAIL, REGRESSION from sprint S01 (tests.test_rounding.test_S01_rounds_half_up)
         agent-cheat: FAIL, missing vs baseline (tests.test_rounding.test_S01_rounds_half_up)
         main again: PASS
...
```

Each example is copied into a temporary git repository, so running them never
changes this checkout. `--keep` leaves them registered in a temporary
`SPRINT_HOME` so you can browse them with `sprint ui`. Stacks without an
installed toolchain are skipped (`--require` makes that a failure, for CI).
