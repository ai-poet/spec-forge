from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
PWCLI_SCRIPT = _REPO_ROOT / "prompts" / "skills" / "playwright" / "scripts" / "playwright_cli.sh"

PLAYWRIGHT_CLI_INSTALL_HINT = (
    "Web UI (playwright-cli): ensure Node.js/npx is available, then run: "
    "npx --yes --package @playwright/cli playwright-cli install-browser"
)


def playwright_cli_wrapper() -> Path:
    return PWCLI_SCRIPT


def ensure_playwright_cli() -> str | None:
    if not shutil.which("npx"):
        return "npx not found; install Node.js for playwright-cli Web UI verification"
    if not PWCLI_SCRIPT.is_file():
        return f"playwright wrapper missing: {PWCLI_SCRIPT}"
    try:
        result = subprocess.run(
            ["npx", "--yes", "--package", "@playwright/cli", "playwright-cli", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"playwright-cli check failed: {exc}"
    if result.returncode != 0:
        return (result.stderr or result.stdout or "playwright-cli --help failed").strip()
    return None
