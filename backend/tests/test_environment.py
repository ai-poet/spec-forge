from __future__ import annotations

import subprocess
from dataclasses import dataclass
from unittest.mock import patch

from specforge import environment


def test_cli_check_missing() -> None:
    with patch("specforge.environment.shutil.which", return_value=None):
        result = environment._cli_check("claude_cli", "Claude Code CLI", "claude", hint="install claude")

    assert result["status"] == "error"
    assert result["message"] == "`claude` not found on PATH"
    assert result["hint"] == "install claude"


def test_cli_check_version_ok() -> None:
    completed = subprocess.CompletedProcess(["codex", "--version"], 0, stdout="codex 1.0\n", stderr="")
    with (
        patch("specforge.environment.shutil.which", return_value="/usr/local/bin/codex"),
        patch("specforge.environment.subprocess.run", return_value=completed),
    ):
        result = environment._cli_check("codex_cli", "Codex CLI", "codex", hint="install codex")

    assert result["status"] == "ok"
    assert result["detail"] == "codex 1.0"
    assert result["hint"] is None


def test_cli_check_version_failed() -> None:
    completed = subprocess.CompletedProcess(["claude", "--version"], 2, stdout="", stderr="bad auth\n")
    with (
        patch("specforge.environment.shutil.which", return_value="/usr/local/bin/claude"),
        patch("specforge.environment.subprocess.run", return_value=completed),
    ):
        result = environment._cli_check("claude_cli", "Claude Code CLI", "claude", hint="install claude")

    assert result["status"] == "error"
    assert result["message"] == "`claude --version` exited 2"
    assert result["detail"] == "bad auth"


@dataclass(frozen=True)
class FakeHolder:
    iteration_id: str
    pid: int


def test_environment_checks_aggregate_ok_warning_and_errors() -> None:
    with (
        patch("specforge.environment._cli_check", side_effect=[
            {"id": "claude_cli", "label": "Claude", "status": "ok", "message": "ok", "detail": None, "hint": None},
            {"id": "codex_cli", "label": "Codex", "status": "error", "message": "missing", "detail": None, "hint": "install"},
        ]),
        patch("specforge.environment.ensure_playwright_cli", return_value=None),
        patch("specforge.environment.PlaywrightUIDriverRunner") as playwright_runner,
        patch("specforge.environment.cua_driver_installed", return_value=True),
        patch("specforge.environment.CuaUIDriverRunner") as cua_runner,
        patch("specforge.environment.read_cua_session_holder", return_value=FakeHolder("iter_1", 123)),
    ):
        playwright_runner.return_value.ensure_available.return_value = "Playwright browsers not installed"
        cua_runner.return_value.ensure_available.return_value = None
        result = environment.environment_checks()

    assert result["status"] == "error"
    checks = {item["id"]: item for item in result["checks"]}  # type: ignore[index]
    assert checks["codex_cli"]["status"] == "error"
    assert checks["web_ui_smoke"]["status"] == "error"
    assert checks["cua_session"]["status"] == "warning"
    assert checks["cua_daemon_permissions"]["status"] == "ok"


def test_environment_checks_aggregate_warning_without_errors() -> None:
    with (
        patch("specforge.environment._cli_check", side_effect=[
            {"id": "claude_cli", "label": "Claude", "status": "ok", "message": "ok", "detail": None, "hint": None},
            {"id": "codex_cli", "label": "Codex", "status": "ok", "message": "ok", "detail": None, "hint": None},
        ]),
        patch("specforge.environment.ensure_playwright_cli", return_value=None),
        patch("specforge.environment.PlaywrightUIDriverRunner") as playwright_runner,
        patch("specforge.environment.cua_driver_installed", return_value=True),
        patch("specforge.environment.CuaUIDriverRunner") as cua_runner,
        patch("specforge.environment.read_cua_session_holder", return_value=FakeHolder("iter_1", 123)),
    ):
        playwright_runner.return_value.ensure_available.return_value = None
        cua_runner.return_value.ensure_available.return_value = None
        result = environment.environment_checks()

    assert result["status"] == "warning"
