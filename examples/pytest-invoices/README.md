# pytest example

Two sprints of a tiny invoicing module. S01 (rounding) is closed and S02 (VAT)
is active. `examples/run-all.sh pytest` checks that:

- the gate passes on `main` and both S02 acceptance criteria are satisfied;
- on the `s01-regression` branch (from `.regression/`), an S02 "simplification"
  that switches to float maths fails with **REGRESSION from sprint S01**;
- on the `agent-cheat` branch (from `.cheat/`), deleting the failing S01 test
  makes plain `pytest` green, but the gate fails with **missing vs baseline**.
