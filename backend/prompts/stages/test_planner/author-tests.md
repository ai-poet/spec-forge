## Author protected tests

Use code test paths under `tests/unit` or `tests/integration`.

For UI tests, write JSON specs under `tests/ui/*.json` with shape {ui_spec_hint}.

Allowed UI actions (snake_case only): {ui_actions}.

Prefer scenario steps that an Agent can execute with **playwright-cli** (`open` → `snapshot` → `click eN`) for `kind: web`, or **cua-driver** (`launch_app` → `get_window_state` → `element_index`) for `kind: native`. Steps are acceptance hints — UI Tester may adapt using live snapshots. Use CSS `selector` only when DOM refs from snapshot are insufficient.

Each test entry must include concrete assertions — not placeholders.
