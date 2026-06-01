# cua-driver (native UI)

Drive **native** specs only (`kind: native`). Follow the no-foreground contract:

- **Never** use `open -a`, `open -b`, `osascript activate`, or `cliclick`.
- Use `cua-driver launch_app` with `bundle_id` / `app_name` from the spec `target`.
- Loop: `get_window_state` → act by `element_index` or text match in `tree_markdown` → re-snapshot to verify.

Recording: `cua-driver recording_start` / `recording_stop` into `tests/ui/recordings/<id>/`.

If CUA session is busy (see runtime notes), mark native specs `warning` with a clear message; do not steal focus from the user.

Install hint: {cua_install_hint}

For full cua-driver skill detail, the agent may also read skills under the project's computer-use tree when present; the operational rules above are mandatory for SpecForge.
