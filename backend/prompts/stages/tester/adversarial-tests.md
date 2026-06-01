## Defects and adversarial tests

JSON shape includes:

`defects:[{{severity:'P0'|'P1'|'P2', path?:string, owner?:'coder'|'tester'|'planner', message:string}}]`

Only propose adversarial tests under `tests/adversarial`.

For each defect set `owner=tester` when the path is under `tests/adversarial/**` or verify/delivery docs; `owner=coder` for `src/**` implementation bugs; `owner=planner` for protected tests under `tests/unit`, `tests/integration`, `tests/ui`.
