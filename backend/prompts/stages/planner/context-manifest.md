## Context manifests (required)

You must include non-empty context manifests (SpecForge writes them as `context/for_coder.jsonl` and `context/for_tester.jsonl`; downstream agents read only these lists):

- **context_for_coder**: [{{"file": "relative/path", "reason": "why Coder must read this"}}]
- **context_for_tester**: [{{"file": "relative/path", "reason": "why Tester must read this"}}]

Include this iteration's planning docs and protected tests in both manifests. Add `docs/03_invariants/*` or `docs/04_decisions/*` only when they exist or you create them for this project.
