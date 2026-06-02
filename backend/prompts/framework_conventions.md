# SpecForge framework rules (injected into agent prompts; not written to user docs/)

## Write zones

| Zone | Path pattern | Owner |
|------|--------------|-------|
| Source | `src/**` (or paths declared in docs/00_convention.md) | Coder |
| Protected tests | `tests/unit`, `tests/integration` | Planner |
| Adversarial tests | `tests/adversarial/**` | Tester |
| Verify docs | `verify_report.md`, `delivery_advice.md`, `ui_*` | Tester |
| PRD | iteration `prd.md` | PRD Planner |
| Test plan | iteration `testing_plan.md` | Test Planner |

- Coder must not edit `docs/**`, protected `tests/**`, or `.specforge/**`.
- Downstream agents read only paths listed in `context/for_coder.jsonl` or `context/for_tester.jsonl`.

## UI acceptance

Do not create `tests/ui/*.json` specs. UI acceptance scenarios live in
`testing_plan.md` under the Manual Tests section, and UI Tester executes them
directly with playwright-cli or cua-driver.

## Package specs

Optional guidelines live under `docs/spec/<package>/<layer>/`. When used, add entries to `docs/spec-index.md` and reference them in context manifests.
