#!/usr/bin/env bash
# Vendored wrapper for @playwright/cli — used by ui_tester Agent (see prompts/stages/ui_tester/playwright-cli.md).
set -euo pipefail
exec npx --yes --package @playwright/cli playwright-cli "$@"
