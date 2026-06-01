from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from specforge.contracts import UITestSpec
from specforge.ui_driver_playwright import (
    PLAYWRIGHT_BROWSERS_MISSING,
    PLAYWRIGHT_PACKAGE_MISSING,
    PlaywrightUIDriverRunner,
)


class FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def type(self, text: str) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class FakeMouse:
    def __init__(self) -> None:
        self.wheels: list[tuple[int, int]] = []

    def wheel(self, x: int, y: int) -> None:
        self.wheels.append((x, y))


class FakeLocator:
    def __init__(self, page: "FakePage", *, selector: str | None = None, text: str | None = None) -> None:
        self._page = page
        self._selector = selector
        self._text = text

    @property
    def first(self) -> "FakeLocator":
        return self

    def click(self, *, timeout: int = 0) -> None:
        self._page.clicked.append(self._text or self._selector or self._page._pending_text)

    def fill(self, text: str) -> None:
        self._page.keyboard.typed.append(text)

    def is_visible(self, *, timeout: int = 0) -> bool:
        if self._selector:
            return self._selector.strip(".") in self._page._content or self._selector in self._page._content
        if self._text:
            return self._text in self._page._content
        return False

    def inner_text(self, *, timeout: int = 0) -> str:
        if self._selector == ".titlebar-timer":
            return "05:00"
        if self._text:
            return self._text
        return self._page._content


class FakePage:
    def __init__(self, *, content: str = "<html>SpecForge UI</html>", url: str = "http://127.0.0.1:5178") -> None:
        self._content = content
        self._url = url
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        self.clicked: list[str] = []
        self._pending_text = ""
        self.screenshots: list[Path] = []
        self.viewport: dict[str, int] | None = None
        self.slept_ms: list[int] = []

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 0) -> None:
        self._url = url

    def content(self) -> str:
        return self._content

    def get_by_text(self, text: str, *, exact: bool = False) -> FakeLocator:
        self._pending_text = text
        return FakeLocator(self, text=text)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector=selector)

    def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.viewport = viewport

    def screenshot(self, *, path: str | Path, full_page: bool = True) -> bytes:
        screenshot_path = Path(path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"png")
        self.screenshots.append(screenshot_path)
        return b"png"


class FakeSession:
    def __init__(self, page: FakePage | None = None) -> None:
        self._page = page or FakePage()
        self.closed = False

    def new_page(self) -> FakePage:
        return self._page

    def close(self) -> None:
        self.closed = True


def test_playwright_runner_assert_text_passes(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "title": "Smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "SpecForge"}],
        }
    )
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession())
    results = runner.run_specs([spec], tmp_path)
    assert len(results) == 1
    assert results[0].status == "passed"
    assert results[0].driver == "playwright"
    assert "找到文本" in results[0].observations[0]


def test_playwright_runner_assert_text_fails(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "title": "Smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "Missing"}],
        }
    )
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession(FakePage(content="<html></html>")))
    results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "failed"
    assert "UI text not found" in (results[0].error or "")


def test_playwright_runner_click_text(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_click",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "click_text", "text": "Submit"}],
        }
    )
    page = FakePage()
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession(page))
    results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "passed", results[0].error
    assert page.clicked == ["Submit"]


def test_playwright_runner_selector_assert_text_and_type_text(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_selector_form",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [
                {"action": "assert_text", "selector": ".titlebar-timer", "value": "05:00"},
                {"action": "type_text", "selector": "input[placeholder='Email']", "value": "test@example.com"},
            ],
        }
    )
    page = FakePage(content='<html><div class="titlebar-timer">05:00</div></html>')
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession(page))
    results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "passed", results[0].error
    assert page.keyboard.typed == ["test@example.com"]


def test_playwright_runner_wait_and_resize_window(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_resize",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [
                {"action": "wait", "value": "100"},
                {"action": "resize_window", "value": "360,420"},
            ],
        }
    )
    page = FakePage(content='<html><div class="titlebar-timer">05:00</div></html>')
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession(page))
    with patch("specforge.ui_driver_playwright.time.sleep") as sleep:
        results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "passed", results[0].error
    sleep.assert_called_once_with(0.1)
    assert page.viewport == {"width": 360, "height": 420}


def test_playwright_runner_assert_text_match_and_visibility(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_assertions",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [
                {"action": "assert_text_match", "selector": ".titlebar-timer", "value": "^\\d{2}:\\d{2}$"},
                {"action": "assert_visible", "selector": ".titlebar-timer"},
                {"action": "assert_missing", "text": "MissingLabel"},
            ],
        }
    )
    page = FakePage(content='<html><div class="titlebar-timer">05:00</div></html>')
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession(page))
    results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "passed", results[0].error


def test_ensure_available_package_missing(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api" or (name == "playwright" and fromlist and "sync_api" in fromlist):
            raise ImportError("no playwright")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert PlaywrightUIDriverRunner().ensure_available() == PLAYWRIGHT_PACKAGE_MISSING


def test_ensure_available_reports_missing_browsers() -> None:
    class BrokenPlaywright:
        def stop(self) -> None:
            return None

        @property
        def chromium(self):
            return self

        def launch(self, *, headless: bool = True):
            raise RuntimeError("Executable doesn't exist at /tmp/fake-chromium")

    class FakeSyncPlaywright:
        def start(self) -> BrokenPlaywright:
            return BrokenPlaywright()

    with patch("playwright.sync_api.sync_playwright", return_value=FakeSyncPlaywright()):
        assert PlaywrightUIDriverRunner().ensure_available() == PLAYWRIGHT_BROWSERS_MISSING


def test_ensure_available_ok_with_session_factory() -> None:
    assert PlaywrightUIDriverRunner(session_factory=lambda: FakeSession()).ensure_available() is None


def test_playwright_runner_native_spec_warns(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "native_smoke",
            "kind": "native",
            "target": {"bundle_id": "com.example.app"},
            "steps": [],
        }
    )
    runner = PlaywrightUIDriverRunner(session_factory=lambda: FakeSession())
    results = runner.run_specs([spec], tmp_path)
    assert results[0].status == "warning"
    assert "native" in (results[0].error or "").lower()
