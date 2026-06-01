from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..core.contracts import UITestResult, UITestSpec, UITestStep


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


def wait_milliseconds(step: UITestStep) -> int:
    raw = (step.value or step.text or "").strip()
    if raw:
        return max(0, int(raw))
    return step.amount * 1000


def parse_window_size(step: UITestStep) -> tuple[int, int]:
    raw = (step.value or step.text or "").strip()
    if not raw:
        raise ValueError("resize_window requires value like '360,420'")
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise ValueError(f"invalid resize_window value: {raw}")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid resize_window dimensions: {raw}")
    return width, height


def step_selector(step: UITestStep) -> str | None:
    if step.selector:
        return step.selector.strip()
    text = (step.text or "").strip()
    if text.startswith((".", "#", "[")):
        return text
    return None


def step_text(step: UITestStep) -> str:
    return (step.text or step.value or "").strip()
