## PRD output

Produce a single **prd** string (Markdown) for this iteration:

- Problem, goals, and scope
- User-visible behavior and acceptance criteria (traceable to the requirements brief)
- Technical stack: runtime, language/framework, package manager/build tooling, test runner, UI/native automation choices when relevant
- Development conventions: source roots, test roots, naming/import style, state/data boundaries, error-handling/logging expectations, and any repo-specific commands Coder/Tester should follow
- Project structure and change targets: existing directories/modules relevant to the request, candidate/suggested files or modules to modify or create, ownership boundaries, no-touch areas, and why each target follows from the requirement
- Architecture and component boundaries (no file-level implementation checklist)
- Functional requirements, non-functional requirements, API/data contracts, observability, failure behavior, testing strategy, risks, and acceptance criteria concrete enough for Coder and Tester to implement and verify without guessing
- Implementation-lock decisions that would be expensive to change later: source of truth/data store, async/background processing model, permission/security boundary, frontend/backend contract ownership, migration/compatibility strategy, external integrations, rollout/fallback requirements, and performance/reliability targets when relevant
- Source-of-truth and change-control rules: what existing docs/code are canonical, what this PRD overrides for this iteration, and what must be reconciled after implementation
- A concise component/status map for touched areas when the repo has multiple modules, agents, jobs, services, or UI surfaces: current state, target state, owner/boundary, dependencies, and explicit in-scope/deferred/out-of-scope calls
- Boundary I/O contracts for each affected workflow, API, agent, background job, or persistent artifact: triggers, reads, mechanisms, writes, durable vs transient state, status vocabulary, and verification evidence
- A lightweight completion contract modeled after goal-oriented planning: objective, done conditions, evidence surfaces, constraints, boundaries, and blocked/stop conditions. Keep this concise for trivial/simple tasks and expand it only when risk or complexity demands it.

The PRD must include these Markdown sections:

- `## Problem, Goals, and Scope`
- `## Completion Contract`
- `## Technical Stack`
- `## Development Conventions`
- `## Project Structure and Change Targets`
- `## Architecture and Boundaries`
- `## Functional Requirements`
- `## Non-Functional Requirements`
- `## API and Data Contracts`
- `## Testing and Acceptance Strategy`
- `## Risks and Locked Decisions`

Treat these technical sections as a built-in technical specification layer inspired by marketplace technical-specification skills. Avoid vague words like "fast", "secure", or "scalable" unless you provide a measurable or verifiable target, boundary, or testable signal. Define ownership for contracts and data shapes instead of leaving them to Coder invention.

Use layered strictness so simple work stays lightweight:

- `trivial`: keep the PRD compact. `## Completion Contract` must include `Objective`, `Done When`, and 1-3 acceptance points with evidence. Other technical sections may be one-line `N/A` entries with a reason.
- `simple`: include a short completion contract, main scope boundaries, and acceptance evidence for the primary path. API/data/migration/security sections may be `N/A` with a reason when truly not applicable.
- `moderate`: include a standard completion contract, explicit `AC-*` acceptance IDs, major boundary I/O, and enough test strategy for Test Planner to map each acceptance point.
- `complex` or high-risk: expand into a strict technical contract with status vocabulary, data/API contracts, concurrency/idempotency, permissions/security, migration/compatibility, failure/retry, rollback/fallback, and evidence for every acceptance point.

Treat work as high-risk, regardless of discovery complexity, when it touches persistent data, migrations, authentication/authorization, user-sensitive data, external integrations, async/background jobs, multi-agent workflow state, cross-service API contracts, billing/payment, destructive actions, or expensive rollback. In high-risk cases, do not leave the relevant locked decision implicit.

In `## Completion Contract`, use this compact shape:

- `Objective`: the user/system outcome this iteration must achieve.
- `Done When`: concrete completion conditions, preferably with stable `AC-*` IDs for non-trivial work.
- `Verification Evidence`: tests, UI states, API responses, database rows, emitted events, generated docs, raw logs, telemetry, or manual checks that prove completion.
- `Constraints and Boundaries`: important limits, non-goals, source roots, write zones, and ownership boundaries.
- `Blocked If`: unresolved decisions or missing inputs that should stop implementation rather than force Coder to guess. For trivial/simple tasks, include only genuinely blocking ambiguity.

Prefer warnings in prose over over-constraining execution: do not inflate trivial/simple tasks with full architecture tables, but never omit the completion signal that tells downstream agents when the work is actually done.

In `## Project Structure and Change Targets`, ground the PRD in the repository without turning Planner guesses into binding implementation instructions:

- Start with a compact map of relevant existing roots, modules, or documents. For example: `frontend/src/app`, `frontend/src/features/<feature>`, `frontend/src/shared/lib`, `backend/src/<package>/main.py`, `backend/src/<package>/storage`, `tests/**`, `docs/**`, or the repo's actual equivalents.
- List candidate change targets as modules, folders, API routes, data models, services, UI surfaces, docs, tests, prompts, jobs, or persistent artifacts. Include whether each target is `modify`, `create`, `remove`, `observe only`, or `N/A`.
- For each target, state the requirement or acceptance ID it supports and the reason it belongs there. Keep this as a suggested map of execution surfaces, not a line-by-line implementation checklist.
- Make clear that these targets are advisory candidate surfaces. Coder must inspect the current repository, validate whether each candidate is still correct, and choose the final files/modules to edit. Coder may deviate from the candidate list when code reality shows a better implementation surface, as long as the PRD requirements, boundaries, no-touch areas, and acceptance evidence remain satisfied.
- Identify no-touch or protected areas when relevant: generated files, planning docs, unrelated modules, protected tests, migration history, user data, config/secrets, or legacy behavior that must remain compatible.
- Align the `context_for_coder` and `context_for_tester` manifests with this section: files named as required context should correspond to the listed target surfaces or evidence surfaces.
- If a target file cannot be known safely from available context, write `candidate` with the discovery reason rather than inventing an exact file path. If the task is trivial, this section may be a short bullet list of affected files or `N/A — no code change`.

Apply these design-contract disciplines:

- Authoritative contract: the PRD is the authoritative pre-build contract for this iteration. If requirements, existing docs, code reality, and prior generated artifacts disagree, identify the precedence and the exact delta instead of blending them silently. Do not overturn discovery decisions; mark contradictions as risks or open questions.
- Status discipline: when changing an existing system, name the canonical status source if one exists, distinguish current state from target state, and list any docs/status trackers that implementation should update or reconcile.
- Component/status map: for multi-part work, include a compact table or bullets covering touched component/stage, current status, target status, owner or source root, dependencies, and whether it is in scope, deferred, or explicitly excluded.
- Boundary I/O: for pipelines, agents, scheduled jobs, APIs, and data flows, describe each boundary with `Trigger`, `Reads`, `Mechanism`, `Writes`, `Persistence`, `Failure/Retry`, and `Verification`. Include provider/model tier or worker ownership when relevant.
- Data-contract precision: define system-boundary inputs and outputs, IDs, status enums, request/response fields, document/event/log artifacts, validation rules, pagination/idempotency/concurrency expectations, and durable vs transient state. Typed contracts and tables take precedence over diagrams or narrative.
- Delta/override discipline: when the task updates an existing spec or behavior, list the exact deltas to apply, the compatibility or migration effect, unchanged behavior, and the old assumptions that must no longer guide Coder or Tester.
- Evidence discipline: acceptance points must name observable evidence: tests, UI states, API responses, database rows, emitted events, generated docs, raw logs, or telemetry signals.

When both frontend and backend work are in scope, the PRD must require frontend/backend separation in `## Architecture and Boundaries`: keep UI and backend source boundaries independent, put backend code under `backend/**`, put frontend code under `frontend/**` by default or `web/**` when the repository already uses that root, communicate through explicit API contracts, avoid UI code depending on backend internals, avoid backend code depending on frontend implementation details, and document ownership for request/response models, validation, error handling, authentication, and integration tests.

In `## Functional Requirements`, make each requirement traceable to the brief and state the expected behavior, user/system actor, state transition, and acceptance evidence. In `## Non-Functional Requirements`, cover reliability, performance, security/permissions, accessibility/UX, observability, compatibility, and maintainability only where relevant, with concrete targets or verification signals. In `## API and Data Contracts`, define schemas/contracts rather than prose-only intent. In `## Testing and Acceptance Strategy`, separate protected/automated checks from manual or UI acceptance. In `## Risks and Locked Decisions`, include open questions, explicit NOT-included items, deferrals, rollback/fallback expectations, and expensive decisions that must be locked before implementation.

When stack choices are not explicitly decided and the repository does not contradict them, use these defaults in `## Technical Stack`:

- Frontend/web UI: React + Vite under `frontend/**` by default, or `web/**` when the repository already uses that root, with componentized UI, Less Modules, and modern large-scale frontend layering such as app shell, pages/routes, features, shared components, state/data services, styles, and assets; explicitly cover UI/UX usability, visual polish, and fault-tolerant loading/empty/error/permission states.
- Backend/API/service work: build on the existing backend framework and code structure under `backend/**`; explicitly cover modular layered design, extensibility, maintainability, and performance across transport routes/controllers, application services/use cases, domain models, data-access/repository/storage, integration adapters, configuration, migrations, and test boundaries. Require a clear layer- or feature-oriented folder structure, and avoid flat backend directories where many unrelated routes, services, schemas, repositories, adapters, and config files are placed side by side.
- Desktop app: Electron with clear main/preload/renderer process boundaries, typed IPC contracts, and a modular renderer organized with the same large-scale frontend layering.
- Mobile app: Capacitor 7 for cross-platform delivery, with shared app/domain/UI layers and platform/native plugin adapters isolated behind stable interfaces.

If the repository has no backend but the feature appears to require one, do not silently choose a backend stack here. Record the ambiguity in the PRD and rely on Discovery to ask the user before final planning proceeds.

When Discovery has explicitly confirmed a new fast backend prototype stack, use exactly one matching structure reference and adapt names to the repo:

- FastAPI: use `backend/app/main.py` or `backend/src/<package>/main.py` as the app entry, split HTTP resources under `routers/` with `APIRouter`, keep shared auth/db/session wiring in `dependencies.py`, start prototype persistence with local SQLite unless the repo/user already selected another database, separate request/response schemas from persistence/domain models, put orchestration in `services/` or use-case modules, isolate persistence in `repositories/` or `storage/`, and place tests in the existing Python test root.
- HonoJS: use `backend/src/index.ts` as the app assembly point, split resources under `backend/src/routes/*.ts` and mount with `app.route()`, avoid Rails-style controller objects unless the repo already uses them, extract reusable handlers with `hono/factory` when useful, start prototype persistence with local SQLite unless the repo/user already selected another database, keep business logic in `services/`, DB/client code in `db/` or `lib/`, middleware/env/types separate, and export `AppType` when frontend/RPC clients need typed contracts.
- Supabase: treat Supabase as the exception to the `backend/**` rule; keep `supabase/config.toml`, `supabase/migrations/*.sql`, `supabase/functions/<name>/index.ts`, `supabase/tests/*.sql` or `*.pg` under the app root, which may be the frontend root (`frontend/` or existing `web/`), with seed data and storage/auth policy config versioned in the repo; model schema, RLS policies, functions, and database tests as migration/test artifacts rather than dashboard-only changes.

These prototype references are optional defaults, not mandatory templates. If the repo already has a backend, summarize and extend the existing structure instead of creating parallel folders. When a backend grows beyond a tiny prototype, require subfolders by layer or bounded feature instead of letting implementation files accumulate in one directory.

If `docs/00_convention.md` is still the default stub, update it with this repository's actual source/test layout and development conventions before returning the artifact. If it is already project-specific, do not overwrite it; summarize the relevant conventions inside the PRD and only add new decisions when needed.

Do **not** author `testing_plan.md`, protected tests, or a separate modification plan — Test Planner runs next.

Use front matter: `doc: prd`, `status: draft`, `owner: prd_planner`.
