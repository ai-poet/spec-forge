## Context manifests (required)

You must include non-empty context manifests (SpecForge writes them as `context/for_coder.jsonl` and `context/for_tester.jsonl`; downstream agents read only these lists):

- **context_for_coder**: [{{"file": "relative/path", "reason": "why Coder must read this"}}]
- **context_for_tester**: [{{"file": "relative/path", "reason": "why Tester must read this"}}]

Include `prd.md` in both manifests. Add `docs/03_invariants/*` or `docs/04_decisions/*` only when they exist or you create them for this project.

When backend work is in scope, also include the relevant existing backend entrypoints, route/API modules, service/use-case modules, domain/schema/model modules, data-access/repository/storage modules, integration adapters, migrations, and tests that Coder or Tester must read. For new FastAPI, HonoJS, or Supabase prototypes with no existing source files yet, include the PRD and any project convention/decision docs that define the chosen backend roots.
