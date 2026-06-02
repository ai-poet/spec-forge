# playwright-cli (Web UI)

Use the bundled wrapper (requires `npx`):

```bash
"{pwcli_wrapper}" open <url> --headed
"{pwcli_wrapper}" snapshot
"{pwcli_wrapper}" click e12
"{pwcli_wrapper}" fill e3 "text"
"{pwcli_wrapper}" press Enter
"{pwcli_wrapper}" screenshot
```

## Core loop

1. `open` the relevant app/page URL from `testing_plan.md`, PRD, or project context.
2. `snapshot` — interact only using refs from the **latest** snapshot (`eN`).
3. Re-snapshot after navigation or major DOM changes; stale refs require a fresh snapshot.
4. Write artifacts under `tests/ui/recordings/<scenario_id>/`.

## Guardrails

- CLI-first only; do not generate `@playwright/test` spec files unless fixing the repo requires it.
- Use `--headed` when visual debugging helps.
- If playwright-cli is unavailable, record `ui_results` with `status: warning` and explain in `failure_notes` / observations.

Install hint: {playwright_install_hint}
