from __future__ import annotations

from pathlib import Path

from specforge.contracts import UITestSpec
from specforge.ui_driver_playwright import PlaywrightUIDriverRunner


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
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    @property
    def first(self) -> "FakeLocator":
        return self

    def click(self, *, timeout: int = 0) -> None:
        self._page.clicked.append(self._page._pending_text)

    def fill(self, text: str) -> None:
        self._page.keyboard.typed.append(text)


class FakePage:
    def __init__(self, *, content: str = "<html>SpecForge UI</html>", url: str = "http://127.0.0.1:5178") -> None:
        self._content = content
        self._url = url
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        self.clicked: list[str] = []
        self._pending_text = ""
        self.screenshots: list[Path] = []

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 0) -> None:
        self._url = url

    def content(self) -> str:
        return self._content

    def get_by_text(self, text: str, *, exact: bool = False) -> FakeLocator:
        self._pending_text = text
        return FakeLocator(self)

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
