+++
id      = "S02"
title   = "VAT"
status  = "active"
goal    = "Invoices add VAT, rounded half-up"
started = 2026-10-10
closed  = ""
out_of_scope = ["reverse charge"]

[[ac]]
id    = "AC1"
desc  = "Standard 20% VAT is added"
tests = ["test_S02_adds_standard_vat"]

[[ac]]
id    = "AC2"
desc  = "VAT on small amounts rounds half-up"
tests = ["/test_S02_vat_rounds_half_up\\[/"]
+++

## Notes / decisions
