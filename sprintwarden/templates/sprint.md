+++
id      = $id
title   = $title
status  = $status          # planned | active | closed
goal    = $goal
started = $started
closed  = ""
out_of_scope = []

# Acceptance criteria. An AC is satisfied when at least one test matches and
# every matching test passed in the latest `sprint gate` run.
# `tests` entries match "<classname>.<name>": a plain string is a substring,
# "/.../" is a regex. Name tests after the sprint, e.g. $example.
[[ac]]
id    = "AC1"
desc  = "Describe the first observable outcome"
tests = []    # e.g. ["${sid}_doesThing"] or ["/${sid}_.*Thing.*/"]
+++

## Notes / decisions
