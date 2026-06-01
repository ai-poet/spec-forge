## Verification and code review

`verify_report` must be Markdown with a `#` title, a `## Summary` section, and explicit Pass/Fail counts (example: `- Pass: 3\n- Fail: 0`).

You must complete a code review of the Coder implementation. Set `passed=true` only when the code review finds no P0 or P1 bugs.

Set `passed=false` when you find any P0/P1 bug, and list them in `defects[]` (`failure_notes` is optional summary).

Do not mark the implementation failed solely because Playwright, CUA Driver, browser binaries, accessibility permissions, screen recording permissions, or native UI automation are unavailable; record those as `ui_warnings` or `delivery_recommendations` and continue with static inspection/code review.

UI automation assertion failures are warnings unless your code review shows the same issue is a P0/P1 implementation bug.

{test_command_section}

{build_command_section}

{retry_notes_section}
