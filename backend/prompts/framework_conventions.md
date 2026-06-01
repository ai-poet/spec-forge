# SpecForge framework rules (injected into agent prompts; not written to user docs/)

## Write zones

| Zone | Path pattern | Owner |
|------|--------------|-------|
| Source | `src/**` (or paths declared in docs/00_convention.md) | Coder |
| Protected tests | `tests/unit`, `tests/integration`, `tests/ui` | Planner |
| Adversarial tests | `tests/adversarial/**` | Tester |
| Verify docs | `verify_report.md`, `delivery_advice.md`, `ui_*` | Tester |
| Planning docs | iteration `system_design.md`, `modification_plan.md`, `testing_plan.md` | Planner |

- Coder must not edit `docs/**`, protected `tests/**`, or `.specforge/**`.
- Downstream agents read only paths listed in `context/for_coder.jsonl` or `context/for_tester.jsonl`.

## UI test specs (`tests/ui/*.json`)

Use snake_case actions only. Shape:

`{id, title, kind: web|native, target: {url|bundle_id|app_name}, steps: [{action, text, value, selector, key, keys, direction, amount}]}`

Allowed actions: assert_text, assert_text_match, assert_missing, assert_visible, click_text, type_text, press_key, hotkey, scroll, screenshot, wait, resize_window.

Web specs may use `selector` for Playwright; native/Cua specs should use visible text / AX-visible controls.

## Package specs

Optional guidelines live under `docs/spec/<package>/<layer>/`. When used, add entries to `docs/spec-index.md` and reference them in context manifests.
