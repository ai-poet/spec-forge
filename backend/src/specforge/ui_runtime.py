from __future__ import annotations

import logging
from typing import TypedDict

from .ui_driver import CuaUIDriverRunner
from .ui_driver_playwright import PLAYWRIGHT_INSTALL_HINT, PlaywrightUIDriverRunner

logger = logging.getLogger(__name__)

UI_DRIVER_INSTALL_HINT = PLAYWRIGHT_INSTALL_HINT


class UIRuntimeStatus(TypedDict):
    playwright: str
    cua: str
    install_hint: str


def ui_runtime_status() -> UIRuntimeStatus:
    playwright_error = PlaywrightUIDriverRunner().ensure_available()
    cua_error = CuaUIDriverRunner().ensure_available()
    return {
        "playwright": "ok" if playwright_error is None else playwright_error,
        "cua": "ok" if cua_error is None else cua_error,
        "install_hint": UI_DRIVER_INSTALL_HINT,
    }


def log_ui_runtime_status() -> UIRuntimeStatus:
    status = ui_runtime_status()
    logger.info(
        "UI runtime: playwright=%s; cua=%s",
        status["playwright"],
        status["cua"],
    )
    if status["playwright"] != "ok":
        logger.info("Playwright install: %s", status["install_hint"])
    return status
