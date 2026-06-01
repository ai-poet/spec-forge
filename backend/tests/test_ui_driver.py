from __future__ import annotations

from pathlib import Path

from contextlib import contextmanager
from typing import Iterator

from specforge.core.contracts import UIDriverRunResult, UITestResult, UITestSpec
from specforge.ui import ui_driver as ui_driver_module
from specforge.ui.ui_driver import CuaCliTransport, CuaUIDriverRunner, UIDriverRunner
from specforge.ui.ui_driver_playwright import PlaywrightUIDriverRunner
from specforge.ui import cua_session


class UnavailableCuaTransport(CuaCliTransport):
    def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
        return 127, "", "cua-driver not found"

    def start_daemon(self) -> tuple[int, str, str]:
        return 127, "", "cua-driver not found"


class FakePlaywrightRunner:
    def ensure_available(self) -> str | None:
        return None

    def run_specs(self, specs: list[UITestSpec], docs_root: Path) -> list[UITestResult]:
        return [
            UITestResult(
                id=spec.id,
                title=spec.title,
                kind=spec.kind,
                status="passed",
                target=spec.target.url or "",
                driver="playwright",
                observations=["playwright ok"],
            )
            for spec in specs
            if spec.kind == "web"
        ]


class AvailableCuaRunner:
    def __init__(self) -> None:
        self.called = False

    def ensure_available(self) -> str | None:
        return None

    def run_specs(self, specs: list[UITestSpec], docs_root: Path) -> list[UITestResult]:
        self.called = True
        return [
            UITestResult(
                id=spec.id,
                title=spec.title,
                kind=spec.kind,
                status="passed",
                target=spec.target.url or spec.target.bundle_id or "",
                driver="cua",
            )
            for spec in specs
        ]


def test_composite_falls_back_to_playwright_for_web(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "SpecForge"}],
        }
    )
    runner = UIDriverRunner(
        transport=UnavailableCuaTransport(),
        playwright_runner=FakePlaywrightRunner(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([spec], tmp_path)
    assert result.fallback == "playwright"
    assert len(result.results) == 1
    assert result.results[0].status == "passed"
    assert result.results[0].driver == "playwright"
    assert result.warning is None


def test_composite_prefers_playwright_for_selector_web_specs(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "focus_timer_header",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_visible", "selector": ".titlebar"}],
        }
    )
    cua = AvailableCuaRunner()
    runner = UIDriverRunner(
        cua_runner=cua,  # type: ignore[arg-type]
        playwright_runner=FakePlaywrightRunner(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([spec], tmp_path)
    assert result.fallback == "playwright"
    assert result.results[0].status == "passed"
    assert result.results[0].driver == "playwright"
    assert cua.called is False


def test_composite_native_warns_when_cua_unavailable(tmp_path: Path) -> None:
    web = UITestSpec.model_validate(
        {"id": "web_smoke", "kind": "web", "target": {"url": "http://127.0.0.1:5178"}, "steps": []}
    )
    native = UITestSpec.model_validate(
        {"id": "native_smoke", "kind": "native", "target": {"bundle_id": "com.example.app"}, "steps": []}
    )
    runner = UIDriverRunner(
        transport=UnavailableCuaTransport(),
        playwright_runner=FakePlaywrightRunner(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([web, native], tmp_path)
    assert result.fallback == "playwright"
    assert result.results[0].status == "passed"
    assert result.results[1].status == "warning"
    assert result.warning is not None


def test_composite_both_unavailable_web_warns(tmp_path: Path) -> None:
    spec = UITestSpec.model_validate(
        {"id": "web_smoke", "kind": "web", "target": {"url": "http://127.0.0.1:5178"}, "steps": []}
    )

    class BrokenPlaywright:
        def ensure_available(self) -> str | None:
            return "Playwright is not installed"

        def run_specs(self, specs: list[UITestSpec], docs_root: Path) -> list[UITestResult]:
            return []

    runner = UIDriverRunner(
        transport=UnavailableCuaTransport(),
        playwright_runner=BrokenPlaywright(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([spec], tmp_path)
    assert result.fallback is None
    assert result.results[0].status == "warning"
    assert result.warning is not None


def test_cua_runner_marks_driver(tmp_path: Path) -> None:
    class OkTransport(CuaCliTransport):
        status_payload = '{"accessibility": true, "screen_recording": true}'

        def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
            if tool == "status":
                return 0, "ok", ""
            if tool == "check_permissions":
                return 0, self.status_payload, ""
            if tool == "launch_app":
                return 0, '{"pid": 1, "windows": [{"window_id": 2}]}', ""
            if tool == "get_window_state":
                return 0, '{"tree_markdown": "SpecForge [1]"}', ""
            if tool in {"recording_start", "recording_stop", "click", "type_text", "press_key", "hotkey", "scroll"}:
                return 0, "{}", ""
            return 127, "", f"unknown tool {tool}"

        def start_daemon(self) -> tuple[int, str, str]:
            return 0, "", ""

    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "SpecForge"}],
        }
    )
    results = CuaUIDriverRunner(OkTransport()).run_specs([spec], tmp_path)
    assert results[0].status == "passed"
    assert results[0].driver == "cua"


def test_cua_selector_steps_fail_before_launching(tmp_path: Path) -> None:
    class RecordingTransport(CuaCliTransport):
        calls: list[str]

        def __init__(self) -> None:
            self.calls = []

        def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
            self.calls.append(tool)
            return 0, "{}", ""

        def start_daemon(self) -> tuple[int, str, str]:
            return 0, "", ""

    transport = RecordingTransport()
    spec = UITestSpec.model_validate(
        {
            "id": "selector_web",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_visible", "selector": ".titlebar"}],
        }
    )
    result = CuaUIDriverRunner(transport).run_specs([spec], tmp_path)[0]
    assert result.status == "failed"
    assert result.driver == "cua"
    assert "CSS selector UI steps require a DOM-capable runner" in (result.error or "")
    assert "launch_app" not in transport.calls


def test_auto_cua_busy_falls_back_to_playwright_for_web(tmp_path: Path, monkeypatch) -> None:
    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "SpecForge"}],
        }
    )
    cua = AvailableCuaRunner()

    @contextmanager
    def busy_session(_iteration_id: str) -> Iterator[None]:
        yield None

    monkeypatch.setattr(ui_driver_module, "try_acquire_cua_session", busy_session)
    monkeypatch.setattr(
        ui_driver_module,
        "read_cua_session_holder",
        lambda: cua_session.CuaSessionHolder("other-iter", 99999),
    )

    runner = UIDriverRunner(
        cua_runner=cua,  # type: ignore[arg-type]
        playwright_runner=FakePlaywrightRunner(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([spec], tmp_path, iteration_id="iter-a")
    assert result.cua_busy is True
    assert result.results[0].status == "passed"
    assert result.results[0].driver == "playwright"
    assert cua.called is False


def test_auto_cua_busy_native_warns(tmp_path: Path, monkeypatch) -> None:
    native = UITestSpec.model_validate(
        {"id": "native_smoke", "kind": "native", "target": {"bundle_id": "com.example.app"}, "steps": []}
    )
    cua = AvailableCuaRunner()

    @contextmanager
    def busy_session(_iteration_id: str) -> Iterator[None]:
        yield None

    monkeypatch.setattr(ui_driver_module, "try_acquire_cua_session", busy_session)
    runner = UIDriverRunner(
        cua_runner=cua,  # type: ignore[arg-type]
        playwright_runner=FakePlaywrightRunner(),  # type: ignore[arg-type]
    )
    result = runner.run_specs([native], tmp_path, iteration_id="iter-a")
    assert result.cua_busy is True
    assert result.results[0].status == "warning"
    assert "only one ui session" in (result.results[0].error or "").lower()


def test_cua_permission_text_not_granted_is_unavailable() -> None:
    class PermissionTransport(CuaCliTransport):
        def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
            if tool == "status":
                return 0, "ok", ""
            if tool == "check_permissions":
                return 0, "❌ Accessibility: NOT granted\n✅ Screen Recording: granted", ""
            return 0, "{}", ""

        def start_daemon(self) -> tuple[int, str, str]:
            return 0, "", ""

    error = CuaUIDriverRunner(PermissionTransport()).ensure_available()
    assert error == "CuaDriver permissions missing: Accessibility or Screen Recording is false"
