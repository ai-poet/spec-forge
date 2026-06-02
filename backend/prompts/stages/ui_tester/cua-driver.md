# cua-driver (native UI)

Drive native UI scenarios only when the manual test requires a native app. Follow the no-foreground contract:

- **Never** use `open -a`, `open -b`, `osascript activate`, or `cliclick`.
- Use `cua-driver launch_app` with the relevant `bundle_id` / `app_name` from `testing_plan.md`, PRD, or project context.
- Loop: `get_window_state` → act by `element_index` or text match in `tree_markdown` → re-snapshot to verify.

Recording: `cua-driver recording_start` / `recording_stop` into `tests/ui/recordings/<scenario_id>/`.

If CUA session is busy (see runtime notes), mark native specs `warning` with a clear message; do not steal focus from the user.

Install hint: {cua_install_hint}

For full cua-driver skill detail, the agent may also read skills under the project's computer-use tree when present; the operational rules above are mandatory for SpecForge.
