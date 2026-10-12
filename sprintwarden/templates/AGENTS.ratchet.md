# Agent rules — test ratchet (mandatory)

This project uses sprintwarden. State lives in `.sprint/`.

1. Never delete, rename, disable or weaken an existing test. If an older test conflicts with the new requirement, STOP and ask the human.
2. Run `sprint gate` before claiming any task is done, and paste its summary.
3. Never edit files in `.sprint/`.
4. Never run `sprint baseline`, `accept-removal` or `allow-skip`; these are human-only.

Test command: `{{TEST_COMMAND}}`
