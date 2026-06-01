#!/usr/bin/env python3
"""Move flat specforge modules into packages and create compatibility shims."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "specforge"

MOVES: dict[str, list[str]] = {
    "core": ["config.py", "models.py", "contracts.py"],
    "storage": ["db.py"],
    "documents": ["docs_io.py", "docs_scaffold.py", "project_paths.py"],
    "agents": ["cli_commands.py", "cli_runner.py", "cli_event_presenter.py", "prompt_loader.py"],
    "policy": ["write_zones.py", "artifact_gate.py", "context_manifest.py", "discovery_options.py"],
    "ui": [
        "ui_runtime.py",
        "playwright_cli.py",
        "cua_bootstrap.py",
        "cua_session.py",
        "ui_driver.py",
        "ui_driver_playwright.py",
        "ui_driver_common.py",
        "native_dialog.py",
    ],
    "runtime": ["events.py", "job_queue.py"],
}

INTERNAL_REPLACEMENTS: list[tuple[str, str]] = [
    ("from .discovery_options import", "from ..policy.discovery_options import"),
    ("from .contracts import", "from .contracts import"),  # within core - unchanged
    ("from .config import", "from .config import"),  # within core/ui - handle per-file
    ("from .models import", "from ..core.models import"),
    ("from .cua_bootstrap import", "from .cua_bootstrap import"),
    ("from .cua_session import", "from .cua_session import"),
    ("from .playwright_cli import", "from .playwright_cli import"),
    ("from .ui_driver_common import", "from .ui_driver_common import"),
    ("from .ui_driver_playwright import", "from .ui_driver_playwright import"),
]


def fix_imports_in_package(pkg: str, filename: str) -> None:
    path = ROOT / pkg / filename
    text = path.read_text(encoding="utf-8")
    if pkg == "core":
        if filename == "contracts.py":
            text = text.replace(
                "from .discovery_options import",
                "from ..policy.discovery_options import",
            )
        # models.py keeps from .contracts
    elif pkg == "policy":
        text = text.replace("from .contracts import", "from ..core.contracts import")
    elif pkg == "ui":
        text = text.replace("from .config import", "from ..core.config import")
        text = text.replace("from .contracts import", "from ..core.contracts import")
    elif pkg == "storage":
        pass
    elif pkg == "documents":
        pass
    elif pkg == "agents":
        pass
    elif pkg == "runtime":
        pass
    path.write_text(text, encoding="utf-8")


def write_package_init(pkg: str, modules: list[str]) -> None:
    init = ROOT / pkg / "__init__.py"
    lines = [f'"""SpecForge {pkg} package."""', ""]
    for mod in modules:
        stem = mod.replace(".py", "")
        lines.append(f"from .{stem} import *  # noqa: F403")
    init.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_shim(old_name: str, pkg: str) -> None:
    stem = old_name.replace(".py", "")
    shim = ROOT / old_name
    shim.write_text(
        f'"""Compatibility shim — use `specforge.{pkg}.{stem}`."""\n'
        f"from specforge.{pkg}.{stem} import *  # noqa: F403\n",
        encoding="utf-8",
    )


def main() -> None:
    for pkg in MOVES:
        (ROOT / pkg).mkdir(parents=True, exist_ok=True)

    for pkg, files in MOVES.items():
        for name in files:
            src = ROOT / name
            dst = ROOT / pkg / name
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))
            fix_imports_in_package(pkg, name)
        write_package_init(pkg, files)
        for name in files:
            write_shim(name, pkg)

    print("Reorganized:", {k: len(v) for k, v in MOVES.items()})


if __name__ == "__main__":
    main()
