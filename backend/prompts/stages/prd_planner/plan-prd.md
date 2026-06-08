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

If `docs/00_convention.md` is still the default stub, update it with this repository's actual source/test layout and development conventions before returning the artifact. If it is already project-specific, do not overwrite it; summarize the relevant conventions inside the PRD and only add new decisions when needed.

Do **not** author `testing_plan.md`, protected tests, or a separate modification plan — Test Planner runs next.

Use front matter: `doc: prd`, `status: draft`, `owner: prd_planner`.
