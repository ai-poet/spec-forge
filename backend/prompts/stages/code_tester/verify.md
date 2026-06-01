## Verification and code review

`verify_report` must be Markdown with a `#` title, a `## Summary` section, and explicit Pass/Fail counts (example: `- Pass: 3\n- Fail: 0`).

You must complete a code review of the Coder implementation. Set `passed=true` only when the code review finds no P0 or P1 bugs.

Set `passed=false` when you find any P0/P1 bug, and list them in `defects[]` (`failure_notes` is optional summary).

Do not mark the implementation failed solely because automated test commands failed to run in the environment; record tooling gaps in `delivery_recommendations` when appropriate.

{test_command_section}

{build_command_section}

{retry_notes_section}
