from __future__ import annotations

from pathlib import Path
from typing import Literal

from .contracts import UITestResult, UITestSpec


def target_label(spec: UITestSpec) -> str:
    if spec.kind == "web":
        return spec.target.url or ""
    return spec.target.bundle_id or spec.target.app_name or ""


def artifact_path(docs_root: Path, path: Path) -> str:
    try:
        return path.relative_to(docs_root).as_posix()
    except ValueError:
        return path.name


def skipped_result(
    spec: UITestSpec,
    warning: str,
    *,
    driver: Literal["cua", "playwright"] | None = None,
) -> UITestResult:
    return UITestResult(
        id=spec.id,
        title=spec.title,
        kind=spec.kind,
        status="warning",
        target=target_label(spec),
        error=warning,
        driver=driver,
    )
