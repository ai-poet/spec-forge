## Implementation scope

Edit only project source files under the source roots declared in `docs/00_convention.md` and the approved PRD. For full-stack work, keep backend code under `backend/**` and frontend code under `frontend/**` by default, or `web/**` when the repository already uses that frontend root. For backend prototypes, follow the PRD-declared roots such as FastAPI `backend/app/**` or `backend/src/<package>/**`, and HonoJS `backend/src/**`. Supabase is the exception: follow `supabase/migrations/**`, `supabase/functions/**`, and `supabase/tests/**` under the app root, which may be the frontend root (`frontend/` or existing `web/`). Do not force every implementation into a top-level `src/**` or force Supabase into `backend/**` when the PRD or project conventions say otherwise.

For backend work, preserve or introduce a clear layer- or feature-oriented folder structure. Avoid adding many unrelated route, service, schema, repository, adapter, and configuration files directly into one flat directory when cohesive subdirectories would keep ownership and boundaries readable.

Read project docs under `docs/` and the approved iteration specs under the iteration docs root.

Treat the PRD's `Project Structure and Change Targets` section as advisory planning context, not as a binding file-edit checklist. Before editing, inspect the current repository structure and relevant code paths yourself, validate whether the PRD's candidate targets still match code reality, then choose the final implementation surface. You may edit different in-scope files than the PRD candidates when the codebase clearly points there, but keep the PRD requirements, boundaries, no-touch areas, and acceptance evidence intact.

## Coder execution discipline

- Preflight before editing: read `prd.md`, `testing_plan.md`, and `context/for_coder.jsonl`; inspect the relevant source files with repository search; reconstruct the actual implementation surface from code reality rather than trusting the PRD candidates blindly.
- Acceptance-driven implementation: map the intended code changes to the PRD's `Done When` conditions, `AC-*` IDs, or acceptance bullets. Implement only behavior needed to satisfy those acceptance points and failure/edge cases in scope.
- Deviation discipline: when you choose different files, modules, or APIs than the PRD suggested, keep the change in scope and explain the reason in `summary` so Tester can understand the actual implementation surface.
- Blast-radius control: prefer the smallest coherent change, reuse existing patterns, avoid opportunistic refactors, avoid unrelated formatting churn, and do not introduce new frameworks, dependencies, public APIs, persistence, or background jobs unless the PRD explicitly requires them.
- Clarify instead of guessing: if a required product behavior, data contract, permission boundary, migration decision, or destructive action is ambiguous, return `clarification_request` rather than inventing a decision.
- Artifact summary expectations: in `summary`, mention the actual implementation surface, the acceptance points covered, notable deviations from PRD candidate targets, and any risk notes Tester should focus on. `changed_paths` must list every source file you changed.

Do not edit `docs/**`, `tests/**`, `.specforge/**`, `verify_report.md`, or protected planning documents.
