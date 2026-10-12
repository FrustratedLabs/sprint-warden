+++
id      = "S01"
title   = "Rounding"
status  = "closed"
goal    = "Amounts are parsed exactly and rounded half-up to cents"
started = 2026-09-28
closed  = 2026-10-09
out_of_scope = ["currencies other than EUR"]

[[ac]]
id    = "AC1"
desc  = "1.005 rounds up to 101 cents"
tests = ["test_S01_rounds_half_up"]

[[ac]]
id    = "AC2"
desc  = "Whole amounts convert exactly"
tests = ["test_S01_whole_amounts"]
+++

## Notes / decisions
- 2026-09-29: use `Decimal`, never floats, for money (agent: claude-code)
