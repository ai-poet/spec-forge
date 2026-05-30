from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import settings
from .contracts import UIArtifactLink, UITestResult, UITestSpec, UITestStep
from .ui_driver_common import (
    artifact_path,
    parse_window_size,
    skipped_result,
    step_selector,
    step_text,
    target_label,
    wait_milliseconds,
)

NATIVE_UNAVAILABLE = "CuaDriver unavailable for native UI"


class PlaywrightPage(Protocol):
    def goto(self, url: str, *, wait_until: str = ..., timeout: int = ...) -> None: ...

    def content(self) -> str: ...

    def get_by_text(self, text: str, *, exact: bool = ...) -> Any: ...

    def locator(self, selector: str) -> Any: ...

    def set_viewport_size(self, viewport: dict[str, int]) -> None: ...

    def screenshot(self, *, path: str | Path, full_page: bool = ...) -> bytes: ...

    def keyboard(self) -> Any: ...

    def mouse(self) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...


class PlaywrightSession(Protocol):
    def new_page(self) -> PlaywrightPage: ...

    def close(self) -> None: ...


PlaywrightFactory = Callable[[], PlaywrightSession]


class PlaywrightUIDriverRunner:
    def __init__(self, session_factory: PlaywrightFactory | None = None, *, browser: str | None = None) -> None:
        self._session_factory = session_factory
        self._browser = browser or settings.playwright_browser

    def ensure_available(self) -> str | None:
        if self._session_factory is not None:
            return None
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            return "Playwright is not installed (pip install specforge[ui] && playwright install chromium)"
        return None

    def run_specs(self, specs: list[UITestSpec], docs_root: Path) -> list[UITestResult]:
        availability = self.ensure_available()
        if availability:
            return [skipped_result(spec, availability, driver="playwright") for spec in specs]
        results: list[UITestResult] = []
        for spec in specs:
            if spec.kind != "web":
                results.append(skipped_result(spec, NATIVE_UNAVAILABLE, driver="playwright"))
                continue
            try:
                results.append(self._run_spec(spec, docs_root))
            except Exception as exc:
                results.append(
                    UITestResult(
                        id=spec.id,
                        title=spec.title,
                        kind=spec.kind,
                        status="failed",
                        target=target_label(spec),
                        error=str(exc),
                        driver="playwright",
                    )
                )
        return results

    def _run_spec(self, spec: UITestSpec, docs_root: Path) -> UITestResult:
        if not spec.target.url:
            raise ValueError("web UI test requires target.url")
        recording_dir = docs_root / "tests" / "ui" / "recordings" / spec.id
        recording_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[UIArtifactLink] = []
        observations: list[str] = []

        session = self._open_session()
        try:
            page = session.new_page()
            page.goto(spec.target.url, wait_until="domcontentloaded", timeout=30_000)
            initial = recording_dir / "initial.png"
            page.screenshot(path=str(initial), full_page=True)
            artifacts.append(UIArtifactLink(label="初始截图", path=artifact_path(docs_root, initial)))

            for index, step in enumerate(spec.steps, start=1):
                screenshot_path = recording_dir / f"step_{index:02d}.png"
                self._run_step(page, step, index, screenshot_path, docs_root, recording_dir, artifacts, observations)
        finally:
            session.close()

        artifacts.append(UIArtifactLink(label="轨迹目录", path=artifact_path(docs_root, recording_dir)))
        return UITestResult(
            id=spec.id,
            title=spec.title,
            kind=spec.kind,
            status="passed",
            target=target_label(spec),
            observations=observations,
            artifacts=artifacts,
            driver="playwright",
        )

    def _run_step(
        self,
        page: PlaywrightPage,
        step: UITestStep,
        index: int,
        screenshot_path: Path,
        docs_root: Path,
        recording_dir: Path,
        artifacts: list[UIArtifactLink],
        observations: list[str],
    ) -> None:
        if step.action == "assert_text":
            expected = step_text(step)
            target = self._step_target_text(page, step)
            if expected not in target:
                raise RuntimeError(f"UI text not found: {expected}")
            observations.append(f"找到文本: {expected}")
        elif step.action == "assert_text_match":
            pattern = (step.value or step.text or "").strip()
            if not pattern:
                raise ValueError("assert_text_match requires value regex pattern")
            target = self._step_target_text(page, step)
            if not re.search(pattern, target):
                raise RuntimeError(f"UI text pattern not matched: {pattern}")
            observations.append(f"文本匹配: {pattern}")
        elif step.action == "assert_missing":
            if self._is_visible(page, step):
                raise RuntimeError(f"UI element still visible: {step.selector or step.text}")
            observations.append(f"元素不可见: {step.selector or step.text}")
        elif step.action == "assert_visible":
            if not self._is_visible(page, step):
                raise RuntimeError(f"UI element not visible: {step.selector or step.text}")
            observations.append(f"元素可见: {step.selector or step.text}")
        elif step.action == "click_text":
            expected = step_text(step)
            page.get_by_text(expected, exact=False).first.click(timeout=10_000)
            page.screenshot(path=str(screenshot_path), full_page=True)
            artifacts.append(UIArtifactLink(label=f"步骤 {index} 截图", path=artifact_path(docs_root, screenshot_path)))
        elif step.action == "type_text":
            text = step_text(step)
            selector = step_selector(step)
            if selector:
                page.locator(selector).first.fill(text)
            else:
                page.keyboard.type(text)
            page.screenshot(path=str(screenshot_path), full_page=True)
        elif step.action == "press_key":
            key = step.key or step.text or "Enter"
            page.keyboard.press(self._playwright_key(key))
            page.screenshot(path=str(screenshot_path), full_page=True)
        elif step.action == "hotkey":
            keys = [self._playwright_key(item) for item in step.keys]
            if keys:
                page.keyboard.press("+".join(keys))
            page.screenshot(path=str(screenshot_path), full_page=True)
        elif step.action == "scroll":
            delta = step.amount * 400
            if step.direction == "down":
                page.mouse.wheel(0, delta)
            elif step.direction == "up":
                page.mouse.wheel(0, -delta)
            elif step.direction == "right":
                page.mouse.wheel(delta, 0)
            else:
                page.mouse.wheel(-delta, 0)
            page.screenshot(path=str(screenshot_path), full_page=True)
        elif step.action == "wait":
            delay_ms = wait_milliseconds(step)
            time.sleep(delay_ms / 1000)
            observations.append(f"等待 {delay_ms}ms")
        elif step.action == "resize_window":
            width, height = parse_window_size(step)
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=str(screenshot_path), full_page=True)
            artifacts.append(UIArtifactLink(label=f"步骤 {index} 视口截图", path=artifact_path(docs_root, screenshot_path)))
            observations.append(f"视口调整为 {width}x{height}")
        elif step.action == "screenshot":
            page.screenshot(path=str(screenshot_path), full_page=True)
            artifacts.append(UIArtifactLink(label=f"截图 {index}", path=artifact_path(docs_root, screenshot_path)))
        else:
            raise RuntimeError(f"unsupported UI action: {step.action}")

    def _step_target_text(self, page: PlaywrightPage, step: UITestStep) -> str:
        selector = step_selector(step)
        if selector:
            locator = page.locator(selector).first
            return str(locator.inner_text(timeout=10_000))
        return page.content()

    def _is_visible(self, page: PlaywrightPage, step: UITestStep) -> bool:
        selector = step_selector(step)
        if selector:
            return bool(page.locator(selector).first.is_visible(timeout=2_000))
        expected = step_text(step)
        if not expected:
            raise ValueError("assert step requires selector or text")
        return bool(page.get_by_text(expected, exact=False).first.is_visible(timeout=2_000))

    def _open_session(self) -> PlaywrightSession:
        if self._session_factory is not None:
            return self._session_factory()
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser_type = getattr(playwright, self._browser, None)
        if browser_type is None:
            playwright.stop()
            raise RuntimeError(f"unsupported Playwright browser: {self._browser}")
        browser = browser_type.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        class _Session:
            def new_page(self) -> PlaywrightPage:
                return page  # type: ignore[return-value]

            def close(self) -> None:
                context.close()
                browser.close()
                playwright.stop()

        return _Session()

    def _playwright_key(self, key: str) -> str:
        normalized = key.strip().lower()
        aliases = {
            "return": "Enter",
            "enter": "Enter",
            "esc": "Escape",
            "escape": "Escape",
            "space": " ",
            "tab": "Tab",
            "backspace": "Backspace",
            "delete": "Delete",
        }
        return aliases.get(normalized, key)
