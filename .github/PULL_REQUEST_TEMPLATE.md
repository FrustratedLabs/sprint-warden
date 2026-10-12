## What and why

## Checklist

- [ ] `python -m pytest -q` passes and `ruff check . && ruff format --check .` are clean
- [ ] New tests are named for the active sprint (`test_S0X_...`, see `sprint status`)
- [ ] No existing test was deleted, skipped or weakened (the gate will tell you)
- [ ] Runtime code is still standard-library only
- [ ] Docs / CHANGELOG updated if behaviour changed
