from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import REPO_ROOT

SWIFT_APP_BUNDLE = Path("/Applications/CuaDriver.app")
RS_APP_BUNDLE = Path("/Applications/CuaDriverRs.app")
RS_HOME_DIR = Path.home() / ".cua-driver-rs"
INSTALL_SCRIPT = REPO_ROOT / "computer-use" / "backend" / "install_cua_driver.py"

CUA_INSTALL_HINT = (
    "python computer-use/backend/install_cua_driver.py  "
    "(macOS: grant Accessibility + Screen Recording for CuaDriver)"
)


def cua_driver_installed() -> bool:
    """Detect Swift cua-driver or cua-driver-rs (aligned with computer-use preflight)."""
    if SWIFT_APP_BUNDLE.exists() or RS_APP_BUNDLE.exists() or RS_HOME_DIR.exists():
        return True
    found = shutil.which("cua-driver")
    if not found:
        return False
    real = os.path.realpath(found)
    return any(tag in real for tag in ("CuaDriver.app", "CuaDriverRs.app", "/.cua-driver-rs/"))


def ensure_cua_driver(*, auto_install: bool = True) -> str | None:
    """Return None when cua-driver is ready, else an error message."""
    if cua_driver_installed():
        return None
    if not auto_install:
        return f"CuaDriver not installed ({CUA_INSTALL_HINT})"
    if not INSTALL_SCRIPT.is_file():
        return f"CuaDriver installer missing: {INSTALL_SCRIPT}"
    proc = subprocess.run(
        [sys.executable, str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit code {proc.returncode}"
        return f"CuaDriver install failed: {detail}"
    if not cua_driver_installed():
        return f"CuaDriver install finished but cua-driver still not detected ({CUA_INSTALL_HINT})"
    return None
