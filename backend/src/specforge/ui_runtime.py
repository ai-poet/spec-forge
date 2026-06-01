from __future__ import annotations

import logging
import os
from typing import TypedDict

from .cua_bootstrap import CUA_INSTALL_HINT, cua_driver_installed, ensure_cua_driver
from .cua_session import read_cua_session_holder
from .ui_driver import CuaUIDriverRunner
from .ui_driver_playwright import PLAYWRIGHT_INSTALL_HINT, PlaywrightUIDriverRunner

logger = logging.getLogger(__name__)

UI_DRIVER_INSTALL_HINT = PLAYWRIGHT_INSTALL_HINT


class UIRuntimeStatus(TypedDict):
    playwright: str
    cua: str
    cua_session: str
    playwright_install_hint: str
    cua_install_hint: str
    install_hint: str


def _cua_runtime_status() -> str:
    if os.getenv("SPECFORGE_CUA_AUTO_INSTALL", "").strip() in {"1", "true", "yes"}:
        if not cua_driver_installed():
            install_error = ensure_cua_driver(auto_install=True)
            if install_error:
                return install_error
    return CuaUIDriverRunner().ensure_available() or "ok"


def _cua_session_status() -> str:
    holder = read_cua_session_holder()
    if holder is None:
        return "idle"
    return f"busy:{holder.iteration_id}"


def ui_runtime_status() -> UIRuntimeStatus:
    playwright_error = PlaywrightUIDriverRunner().ensure_available()
    cua_status = _cua_runtime_status()
    return {
        "playwright": "ok" if playwright_error is None else playwright_error,
        "cua": cua_status,
        "cua_session": _cua_session_status(),
        "playwright_install_hint": PLAYWRIGHT_INSTALL_HINT,
        "cua_install_hint": CUA_INSTALL_HINT,
        "install_hint": PLAYWRIGHT_INSTALL_HINT,
    }


def log_ui_runtime_status() -> UIRuntimeStatus:
    status = ui_runtime_status()
    logger.info(
        "UI runtime: playwright=%s; cua=%s",
        status["playwright"],
        status["cua"],
    )
    if status["playwright"] != "ok":
        logger.info("Playwright install: %s", status["playwright_install_hint"])
    if status["cua"] != "ok":
        logger.info("CuaDriver install: %s", status["cua_install_hint"])
    return status
