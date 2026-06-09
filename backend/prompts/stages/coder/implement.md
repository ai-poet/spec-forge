## Implementation scope

Edit only project source files under `src/**` or the source roots declared in `docs/00_convention.md` and the approved PRD. For backend prototypes, follow the PRD-declared roots such as FastAPI `app/**` or `src/<package>/**`, HonoJS `src/**`, or Supabase `supabase/migrations/**` and `supabase/functions/**`; do not force every backend into `src/**` when the PRD or project conventions say otherwise.

For backend work, preserve or introduce a clear layer- or feature-oriented folder structure. Avoid adding many unrelated route, service, schema, repository, adapter, and configuration files directly into one flat directory when cohesive subdirectories would keep ownership and boundaries readable.

Read project docs under `docs/` and the approved iteration specs under the iteration docs root.

Do not edit `docs/**`, `tests/**`, `.specforge/**`, `verify_report.md`, or protected planning documents.
