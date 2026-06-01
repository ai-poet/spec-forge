## Author protected tests

Use code test paths under `tests/unit` or `tests/integration`.

For UI tests, write JSON specs under `tests/ui/*.json` with shape {ui_spec_hint}.

Allowed UI actions (snake_case only): {ui_actions}.

Prefer `assert_text` / visible-label steps for Web UI when Playwright may be unavailable. Use CSS `selector` only when DOM-level targeting is required (SpecForge runs selector Web specs via Playwright: `pip install -e "backend/.[ui]"` and `playwright install chromium`).
