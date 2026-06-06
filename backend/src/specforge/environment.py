from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from typing import Literal

from .ui.cua_bootstrap import CUA_INSTALL_HINT, cua_driver_installed
from .ui.cua_session import read_cua_session_holder
from .ui.playwright_cli import PLAYWRIGHT_CLI_INSTALL_HINT, ensure_playwright_cli
from .ui.ui_driver import CuaUIDriverRunner
from .ui.ui_driver_playwright import PLAYWRIGHT_INSTALL_HINT, PlaywrightUIDriverRunner
from .agents.providers import PROVIDERS

EnvironmentStatus = Literal["ok", "warning", "error"]

CLAUDE_INSTALL_HINT = "Install Claude Code CLI and ensure `claude` is available on PATH."
CODEX_INSTALL_HINT = "Install the OpenAI Codex Python SDK with `pip install openai-codex` and authenticate Codex."


def environment_checks() -> dict[str, object]:
    checks = [
        _provider_cli_check("claude", "Claude Code Provider", "claude", CLAUDE_INSTALL_HINT),
        _codex_sdk_check(),
        _playwright_cli_check(),
        _web_ui_smoke_check(),
        _cua_driver_check(),
        _cua_daemon_permissions_check(),
        _cua_session_check(),
    ]
    return {
        "status": _aggregate_status([check["status"] for check in checks]),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def _provider_cli_check(provider_id: str, label: str, binary: str, hint: str) -> dict[str, object]:
    check = dict(_cli_check(f"{provider_id}_cli", label, binary, hint=hint))
    provider = PROVIDERS.provider(provider_id)  # type: ignore[arg-type]
    check["provider"] = provider_id
    check["version"] = check.get("detail")
    check["capabilities"] = provider.describe().capabilities
    return check


def _codex_sdk_check() -> dict[str, object]:
    provider = PROVIDERS.provider("codex")
    doctor = provider.doctor()
    return {
        "id": "codex_sdk",
        "label": "Codex SDK Provider",
        "status": doctor.status,
        "message": doctor.message,
        "detail": doctor.detail,
        "hint": doctor.install_hint,
        "provider": "codex",
        "version": doctor.version,
        "capabilities": doctor.capabilities,
    }


def _aggregate_status(statuses: list[str]) -> EnvironmentStatus:
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "warning" for status in statuses):
        return "warning"
    return "ok"


def _cli_check(check_id: str, label: str, binary: str, *, hint: str) -> dict[str, str | None]:
    found = shutil.which(binary)
    if not found:
        return {
            "id": check_id,
            "label": label,
            "status": "error",
            "message": f"`{binary}` not found on PATH",
            "detail": None,
            "hint": hint,
        }
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "id": check_id,
            "label": label,
            "status": "error",
            "message": f"`{binary} --version` failed",
            "detail": str(exc),
            "hint": hint,
        }
    detail = _compact_output(result.stdout or result.stderr)
    if result.returncode != 0:
        return {
            "id": check_id,
            "label": label,
            "status": "error",
            "message": f"`{binary} --version` exited {result.returncode}",
            "detail": detail,
            "hint": hint,
        }
    return {
        "id": check_id,
        "label": label,
        "status": "ok",
        "message": "Available",
        "detail": detail or found,
        "hint": None,
    }


def _compact_output(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[0][:240]


def _playwright_cli_check() -> dict[str, str | None]:
    error = ensure_playwright_cli()
    if error:
        return {
            "id": "playwright_cli",
            "label": "playwright-cli",
            "status": "error",
            "message": "playwright-cli unavailable",
            "detail": error,
            "hint": PLAYWRIGHT_CLI_INSTALL_HINT,
        }
    return {
        "id": "playwright_cli",
        "label": "playwright-cli",
        "status": "ok",
        "message": "Available",
        "detail": None,
        "hint": None,
    }


def _web_ui_smoke_check() -> dict[str, str | None]:
    error = PlaywrightUIDriverRunner().ensure_available()
    if error:
        return {
            "id": "web_ui_smoke",
            "label": "Web UI smoke",
            "status": "error",
            "message": "Python Playwright unavailable",
            "detail": error,
            "hint": PLAYWRIGHT_INSTALL_HINT,
        }
    return {
        "id": "web_ui_smoke",
        "label": "Web UI smoke",
        "status": "ok",
        "message": "Browser automation available",
        "detail": None,
        "hint": None,
    }


def _cua_driver_check() -> dict[str, str | None]:
    if not cua_driver_installed():
        return {
            "id": "cua_driver",
            "label": "CuaDriver install",
            "status": "error",
            "message": "CuaDriver not installed",
            "detail": None,
            "hint": CUA_INSTALL_HINT,
        }
    return {
        "id": "cua_driver",
        "label": "CuaDriver install",
        "status": "ok",
        "message": "Installed",
        "detail": None,
        "hint": None,
    }


def _cua_daemon_permissions_check() -> dict[str, str | None]:
    error = CuaUIDriverRunner().ensure_available()
    if error:
        return {
            "id": "cua_daemon_permissions",
            "label": "CuaDriver daemon",
            "status": "error",
            "message": "CuaDriver daemon or permissions unavailable",
            "detail": error,
            "hint": CUA_INSTALL_HINT,
        }
    return {
        "id": "cua_daemon_permissions",
        "label": "CuaDriver daemon",
        "status": "ok",
        "message": "Daemon and permissions available",
        "detail": None,
        "hint": None,
    }


def _cua_session_check() -> dict[str, str | None]:
    holder = read_cua_session_holder()
    if holder is None:
        return {
            "id": "cua_session",
            "label": "CuaDriver session",
            "status": "ok",
            "message": "idle",
            "detail": None,
            "hint": None,
        }
    return {
        "id": "cua_session",
        "label": "CuaDriver session",
        "status": "warning",
        "message": f"busy:{holder.iteration_id}",
        "detail": f"Held by pid {holder.pid}",
        "hint": "Only one CuaDriver UI session can run at a time; web checks can still use Playwright.",
    }
