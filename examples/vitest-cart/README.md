# Vitest example

Two sprints of a tiny cart (plain ES modules, no build step). S01 (totals) is
closed and S02 (coupons) is active. Tests are attributed with
`describe("[S01] …")`. On the `s01-regression` branch an S02 refactor drops the
quantity, and the gate reports **REGRESSION from sprint S01**.

`npm install` first; `examples/run-all.sh vitest` does it for you.
