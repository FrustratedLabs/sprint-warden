+++
id      = "S02"
title   = "Ratchet MVP"
status  = "closed"          # planned | active | closed
goal    = "`sprint init --ratchet-only` protects every existing test in one command"
started = 2026-10-12
closed  = 2026-10-12
out_of_scope = ["agent hooks", "sprint lifecycle commands", "dashboard"]

[[ac]]
id    = "AC1"
desc  = "init --ratchet-only detects the stack, runs the first gate and writes the baseline"
tests = ["test_S02_init_ratchet_only_is_useful_in_one_command", "test_S02_init_autodetects_and_requires_a_stack"]

[[ac]]
id    = "AC2"
desc  = "A regression, a deleted test, a new skip and a ratchet drop each fail the gate with a clear message"
tests = [
  "test_S02_regression_is_labelled_with_its_sprint",
  "test_S02_deleted_test_fails_until_a_human_accepts_it",
  "test_S02_new_skip_fails_until_allowed",
  "test_S02_ratchet_drop_fails_even_when_missing_check_is_off",
]

[[ac]]
id    = "AC3"
desc  = "baseline / accept-removal / allow-skip are human-only and require a clean, passing tree"
tests = ["/test_S02_(baseline_requires|i_am_human|deleted_test_fails)/"]

[[ac]]
id    = "AC4"
desc  = "CI compares against the main branch's baseline, so a tampered baseline can't hide a deletion"
tests = ["test_S02_baseline_ref_ignores_tampered_branch_baseline"]
+++

## Notes / decisions
- 2026-10-12: acceptances are time-scoped to the baseline they follow (D-005) (agent: claude-code)
- 2026-10-12: Stop-hook change detection uses a content fingerprint, not just porcelain (D-004) (agent: claude-code)
