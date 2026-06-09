## Implementation scope

Edit only project source files under the source roots declared in `docs/00_convention.md` and the approved PRD. For full-stack work, keep backend code under `backend/**` and frontend code under `frontend/**` by default, or `web/**` when the repository already uses that frontend root. For backend prototypes, follow the PRD-declared roots such as FastAPI `backend/app/**` or `backend/src/<package>/**`, and HonoJS `backend/src/**`. Supabase is the exception: follow `supabase/migrations/**`, `supabase/functions/**`, and `supabase/tests/**` under the app root, which may be the frontend root (`frontend/` or existing `web/`). Do not force every implementation into a top-level `src/**` or force Supabase into `backend/**` when the PRD or project conventions say otherwise.

For backend work, preserve or introduce a clear layer- or feature-oriented folder structure. Avoid adding many unrelated route, service, schema, repository, adapter, and configuration files directly into one flat directory when cohesive subdirectories would keep ownership and boundaries readable.

Read project docs under `docs/` and the approved iteration specs under the iteration docs root.

Do not edit `docs/**`, `tests/**`, `.specforge/**`, `verify_report.md`, or protected planning documents.
