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

When stack choices are not explicitly decided and the repository does not contradict them, use these defaults in `## Technical Stack`:

- Frontend/web UI: React + Vite, componentized UI, Less Modules, and modern large-scale frontend layering such as app shell, pages/routes, features, shared components, state/data services, styles, and assets; explicitly cover UI/UX usability, visual polish, and fault-tolerant loading/empty/error/permission states.
- Backend/API/service work: build on the existing backend framework and code structure already present in the repository; explicitly cover modular layered design, extensibility, maintainability, and performance across route/controller, application service, domain model, data-access, integration, and test boundaries.
- Desktop app: Electron with clear main/preload/renderer process boundaries, typed IPC contracts, and a modular renderer organized with the same large-scale frontend layering.
- Mobile app: Capacitor 7 for cross-platform delivery, with shared app/domain/UI layers and platform/native plugin adapters isolated behind stable interfaces.

If the repository has no backend but the feature appears to require one, do not silently choose a backend stack here. Record the ambiguity in the PRD and rely on Discovery to ask the user before final planning proceeds.

If `docs/00_convention.md` is still the default stub, update it with this repository's actual source/test layout and development conventions before returning the artifact. If it is already project-specific, do not overwrite it; summarize the relevant conventions inside the PRD and only add new decisions when needed.

Do **not** author `testing_plan.md`, protected tests, or a separate modification plan — Test Planner runs next.

Use front matter: `doc: prd`, `status: draft`, `owner: prd_planner`.
