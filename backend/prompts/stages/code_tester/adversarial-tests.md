# Adversarial tests and defect ownership

When reporting defects in the Code Tester artifact, use:

`defects:[{{severity:'P0'|'P1'|'P2', path?:string, owner?:'coder'|'code_tester'|'test_planner', message:string}}]`

For each defect set `owner=code_tester` when the path is under `tests/adversarial/**` or verify/delivery docs; `owner=coder` for `src/**` implementation bugs; `owner=test_planner` for protected tests under `tests/unit`, `tests/integration`, `tests/ui`.
