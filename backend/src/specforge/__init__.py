"""SpecForge backend package."""

from __future__ import annotations

import sys

from .ui import ui_driver_playwright as _ui_driver_playwright

sys.modules.setdefault(__name__ + ".ui_driver_playwright", _ui_driver_playwright)
