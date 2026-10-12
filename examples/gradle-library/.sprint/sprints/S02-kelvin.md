+++
id      = "S02"
title   = "Kelvin"
status  = "active"
goal    = "Convert Celsius to Kelvin and reject impossible temperatures"
started = 2026-10-10
closed  = ""

[[ac]]
id    = "AC1"
desc  = "Celsius converts to Kelvin"
tests = ["[S02] converts Celsius to Kelvin"]

[[ac]]
id    = "AC2"
desc  = "Below absolute zero is rejected"
tests = ["/absolute zero/"]
+++

## Notes / decisions
