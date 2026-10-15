<!-- sprintwarden:begin (managed by `sprint init`; edit outside this block) -->
# Agent rules — sprint workflow (mandatory)

This project uses sprintwarden. State lives in `.sprint/`.

1. Before any work, run `sprint status` and read the active sprint file in `.sprint/sprints/`.
2. Only implement what is in the active sprint's goal and acceptance criteria. Anything else → ask.
3. Write tests for each acceptance criterion first. Test names MUST start with the active sprint ID (after any `test_`/`Test_` prefix your framework requires), e.g. `test_S08_does_thing`.
4. Never delete, rename, disable or weaken an existing test. If an older test conflicts with the new requirement, STOP and ask the human.
5. Run `sprint gate` before claiming any task is done, and paste its summary.
6. Record notable decisions with `sprint note "<decision>"` (it appends to "Notes / decisions" in the sprint file, with date and agent name).
7. Never edit files in `.sprint/` other than the active sprint's notes.
8. Never run `sprint close`, `sprint baseline`, `accept-removal` or `allow-skip`; these are human-only.

Test command: `python -m pytest -q -p no:cacheprovider --junitxml=.sprint/out/junit.xml`
<!-- sprintwarden:end -->
