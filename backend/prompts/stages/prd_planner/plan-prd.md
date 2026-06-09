## PRD output

Produce a single **prd** string (Markdown) for this iteration:

- Problem, goals, and scope
- User-visible behavior and acceptance criteria (traceable to the requirements brief)
- Technical stack: runtime, language/framework, package manager/build tooling, test runner, UI/native automation choices when relevant
- Development conventions: source roots, test roots, naming/import style, state/data boundaries, error-handling/logging expectations, and any repo-specific commands Coder/Tester should follow
- Architecture and component boundaries (no file-level implementation checklist)

The PRD must include these Markdown sections:

- `## Technical Stack`
- `## Development Conventions`
- `## Architecture and Boundaries`

When both frontend and backend work are in scope, the PRD must require frontend/backend separation in `## Architecture and Boundaries`: keep UI and backend source boundaries independent, communicate through explicit API contracts, avoid UI code depending on backend internals, avoid backend code depending on frontend implementation details, and document ownership for request/response models, validation, error handling, authentication, and integration tests.

When stack choices are not explicitly decided and the repository does not contradict them, use these defaults in `## Technical Stack`:

- Frontend/web UI: React + Vite, componentized UI, Less Modules, and modern large-scale frontend layering such as app shell, pages/routes, features, shared components, state/data services, styles, and assets; explicitly cover UI/UX usability, visual polish, and fault-tolerant loading/empty/error/permission states.
- Backend/API/service work: build on the existing backend framework and code structure already present in the repository; explicitly cover modular layered design, extensibility, maintainability, and performance across transport routes/controllers, application services/use cases, domain models, data-access/repository/storage, integration adapters, configuration, migrations, and test boundaries.
- Desktop app: Electron with clear main/preload/renderer process boundaries, typed IPC contracts, and a modular renderer organized with the same large-scale frontend layering.
- Mobile app: Capacitor 7 for cross-platform delivery, with shared app/domain/UI layers and platform/native plugin adapters isolated behind stable interfaces.

If the repository has no backend but the feature appears to require one, do not silently choose a backend stack here. Record the ambiguity in the PRD and rely on Discovery to ask the user before final planning proceeds.

When Discovery has explicitly confirmed a new fast backend prototype stack, use exactly one matching structure reference and adapt names to the repo:

- FastAPI: use `app/main.py` or `src/<package>/main.py` as the app entry, split HTTP resources under `routers/` with `APIRouter`, keep shared auth/db/session wiring in `dependencies.py`, start prototype persistence with local SQLite unless the repo/user already selected another database, separate request/response schemas from persistence/domain models, put orchestration in `services/` or use-case modules, isolate persistence in `repositories/` or `storage/`, and place tests in the existing Python test root.
- HonoJS: use `src/index.ts` as the app assembly point, split resources under `src/routes/*.ts` and mount with `app.route()`, avoid Rails-style controller objects unless the repo already uses them, extract reusable handlers with `hono/factory` when useful, start prototype persistence with local SQLite unless the repo/user already selected another database, keep business logic in `services/`, DB/client code in `db/` or `lib/`, middleware/env/types separate, and export `AppType` when frontend/RPC clients need typed contracts.
- Supabase: keep `supabase/config.toml`, `supabase/migrations/*.sql`, `supabase/functions/<name>/index.ts`, `supabase/tests/*.sql` or `*.pg`, seed data, and storage/auth policy config versioned in the repo; model schema, RLS policies, functions, and database tests as migration/test artifacts rather than dashboard-only changes.

These prototype references are optional defaults, not mandatory templates. If the repo already has a backend, summarize and extend the existing structure instead of creating parallel folders.

If `docs/00_convention.md` is still the default stub, update it with this repository's actual source/test layout and development conventions before returning the artifact. If it is already project-specific, do not overwrite it; summarize the relevant conventions inside the PRD and only add new decisions when needed.

Do **not** author `testing_plan.md`, protected tests, or a separate modification plan — Test Planner runs next.

Use front matter: `doc: prd`, `status: draft`, `owner: prd_planner`.
