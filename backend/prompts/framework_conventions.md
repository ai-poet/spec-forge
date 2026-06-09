# SpecForge framework rules (injected into agent prompts; not written to user docs/)

## Write zones

| Zone | Path pattern | Owner |
|------|--------------|-------|
| Source | frontend roots (`frontend/**` or existing `web/**`), backend roots (`backend/**`), Supabase roots (`supabase/**` under the app root), or project-specific roots declared in docs/00_convention.md / PRD | Coder |
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

## Default technology preferences

When requirements leave the stack open, prefer:

- Frontend/web UI: React + Vite under `frontend/**` by default, or `web/**` when the repository already uses that root, with componentized UI, Less Modules, and modern large-scale frontend layering such as app shell, pages/routes, features, shared components, state/data services, styles, and assets; give special attention to UI/UX usability, visual polish, and fault-tolerant interaction states.
- Backend/API/service work: keep backend implementation under `backend/**` and extend the existing backend architecture, framework, routing style, data layer, and test conventions already present in the repository; give special attention to modular layered design, extensibility, maintainability, and performance across transport routes/controllers, application services/use cases, domain models, data-access/repository/storage, integration adapters, migrations, configuration, and tests. Organize backend code into clear layer- or feature-oriented folders, and avoid flat directories where many unrelated route, service, schema, repository, adapter, and configuration files are spread side by side.
- Fast backend prototypes: only after Discovery confirms a new backend stack, use one clear structure reference under `backend/**` instead of a vague backend. For FastAPI, prefer `backend/app/main.py` or `backend/src/<package>/main.py`, `routers/` with `APIRouter`, `dependencies.py`, local SQLite first for prototype persistence, `schemas/models`, `services/`, and `repositories/` or `storage/`. For HonoJS, prefer `backend/src/index.ts`, `backend/src/routes/*.ts` mounted with `app.route()`, optional `hono/factory` handlers, local SQLite first for prototype persistence, `services/`, `db/` or `lib/`, middleware/env/types, and exported `AppType` for typed RPC clients. Supabase is the exception to the `backend/**` rule: keep `supabase/config.toml`, `supabase/migrations/*.sql`, `supabase/functions/<name>/index.ts`, `supabase/tests/*.sql` or `*.pg` under the app root, which may be the frontend root (`frontend/` or existing `web/`), with seed data, schema/RLS policies, functions, and database tests versioned in repo. For every backend stack, prefer cohesive subdirectories by layer or bounded feature over placing many implementation files directly in one folder.
- Desktop app: Electron with clear main/preload/renderer process boundaries, typed IPC contracts, and a modular renderer organized with the same large-scale frontend layering.
- Mobile app: Capacitor 7 for cross-platform delivery, with shared app/domain/UI layers and platform/native plugin adapters isolated behind stable interfaces.

If the repository does not have an existing backend and the requested feature may need one, Planner Discovery should ask the user whether to add a backend and what backend stack/runtime to use instead of assuming one.
