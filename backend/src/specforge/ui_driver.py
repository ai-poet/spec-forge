from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import UIArtifactLink, UIDriverRunResult, UITestResult, UITestSpec


class UIDriverTransport(Protocol):
    def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
        ...

    def start_daemon(self) -> tuple[int, str, str]:
        ...


@dataclass
class CuaCliTransport:
    binary: str = "cua-driver"

    def run(self, tool: str, payload: dict | None = None, *, timeout: int = 30) -> tuple[int, str, str]:
        if tool == "recording_start":
            output_dir = "" if payload is None else str(payload.get("output_dir", ""))
            command = [self.binary, "recording", "start", output_dir]
            return self._run_command(command, timeout=timeout)
        if tool == "recording_stop":
            return self._run_command([self.binary, "recording", "stop"], timeout=timeout)
        command = [self.binary, tool]
        if payload is not None:
            command.append(json.dumps(payload, ensure_ascii=False))
        return self._run_command(command, timeout=timeout)

    def _run_command(self, command: list[str], *, timeout: int) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            return 127, "", str(exc)
        except subprocess.TimeoutExpired as exc:
            return 124, exc.stdout or "", exc.stderr or f"{' '.join(command)} timed out"
        return proc.returncode, proc.stdout, proc.stderr

    def start_daemon(self) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["open", "-n", "-g", "-a", "CuaDriver", "--args", "serve"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as exc:
            return 127, "", str(exc)
        except subprocess.TimeoutExpired as exc:
            return 124, exc.stdout or "", exc.stderr or "CuaDriver daemon start timed out"
        return proc.returncode, proc.stdout, proc.stderr


class UIDriverRunner:
    def __init__(self, transport: UIDriverTransport | None = None) -> None:
        self.transport = transport or CuaCliTransport()

    def run_specs(self, specs: list[UITestSpec], docs_root: Path) -> UIDriverRunResult:
        if not specs:
            return UIDriverRunResult(available=True, results=[])
        availability = self._ensure_available()
        if availability:
            return UIDriverRunResult(
                available=False,
                warning=availability,
                results=[self._skipped_result(spec, availability) for spec in specs],
            )

        results: list[UITestResult] = []
        for spec in specs:
            try:
                results.append(self._run_spec(spec, docs_root))
            except Exception as exc:
                results.append(
                    UITestResult(
                        id=spec.id,
                        title=spec.title,
                        kind=spec.kind,
                        status="failed",
                        target=self._target_label(spec),
                        error=str(exc),
                    )
                )
        return UIDriverRunResult(available=True, results=results)

    def _ensure_available(self) -> str | None:
        code, stdout, stderr = self.transport.run("status", timeout=5)
        if code:
            start_code, _, start_err = self.transport.start_daemon()
            if start_code:
                return f"CuaDriver daemon unavailable: {start_err or stderr or 'status failed'}"
            time.sleep(0.5)
            code, stdout, stderr = self.transport.run("status", timeout=5)
            if code:
                return f"CuaDriver status failed: {stderr or stdout}"
        code, stdout, stderr = self.transport.run("check_permissions", {"prompt": False}, timeout=10)
        if code:
            return f"CuaDriver permission check failed: {stderr or stdout}"
        text = f"{stdout}\n{stderr}".lower()
        if '"accessibility": false' in text or '"screen_recording": false' in text:
            return "CuaDriver permissions missing: Accessibility or Screen Recording is false"
        return None

    def _run_spec(self, spec: UITestSpec, docs_root: Path) -> UITestResult:
        launch_payload = self._launch_payload(spec)
        code, stdout, stderr = self.transport.run("launch_app", launch_payload, timeout=30)
        if code:
            raise RuntimeError(stderr or stdout or "launch_app failed")
        launch = self._json(stdout)
        pid = launch.get("pid")
        windows = launch.get("windows") or []
        window_id = windows[0].get("window_id") if windows else None
        if pid is None or window_id is None:
            raise RuntimeError("launch_app did not return pid/window_id")

        recording_dir = docs_root / "tests" / "ui" / "recordings" / spec.id
        recording_dir.mkdir(parents=True, exist_ok=True)
        self.transport.run("recording_start", {"output_dir": str(recording_dir)}, timeout=10)

        artifacts: list[UIArtifactLink] = []
        observations: list[str] = []
        state = self._snapshot(pid, window_id, recording_dir / "initial.png")
        artifacts.append(UIArtifactLink(label="初始截图", path=self._artifact_path(docs_root, recording_dir / "initial.png")))
        tree = str(state.get("tree_markdown") or "")

        try:
            for index, step in enumerate(spec.steps, start=1):
                if step.action == "assert_text":
                    expected = step.text or step.value or ""
                    if expected not in tree:
                        raise RuntimeError(f"UI text not found: {expected}")
                    observations.append(f"找到文本: {expected}")
                elif step.action == "click_text":
                    expected = step.text or step.value or ""
                    element_index = self._find_element_index(tree, expected)
                    if element_index is None:
                        raise RuntimeError(f"click target not found: {expected}")
                    self._action("click", {"pid": pid, "window_id": window_id, "element_index": element_index})
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    artifacts.append(UIArtifactLink(label=f"步骤 {index} 截图", path=self._artifact_path(docs_root, recording_dir / f"step_{index:02d}.png")))
                    tree = str(state.get("tree_markdown") or "")
                elif step.action == "type_text":
                    self._action("type_text", {"pid": pid, "window_id": window_id, "text": step.text or step.value or ""})
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    tree = str(state.get("tree_markdown") or "")
                elif step.action == "press_key":
                    self._action("press_key", {"pid": pid, "window_id": window_id, "key": step.key or step.text or "return"})
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    tree = str(state.get("tree_markdown") or "")
                elif step.action == "hotkey":
                    self._action("hotkey", {"pid": pid, "window_id": window_id, "keys": step.keys})
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    tree = str(state.get("tree_markdown") or "")
                elif step.action == "scroll":
                    self._action("scroll", {"pid": pid, "window_id": window_id, "direction": step.direction, "amount": step.amount, "by": "page"})
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    tree = str(state.get("tree_markdown") or "")
                elif step.action == "screenshot":
                    state = self._snapshot(pid, window_id, recording_dir / f"step_{index:02d}.png")
                    artifacts.append(UIArtifactLink(label=f"截图 {index}", path=self._artifact_path(docs_root, recording_dir / f"step_{index:02d}.png")))
                    tree = str(state.get("tree_markdown") or "")
        finally:
            self.transport.run("recording_stop", timeout=10)

        artifacts.append(UIArtifactLink(label="轨迹目录", path=self._artifact_path(docs_root, recording_dir)))
        return UITestResult(
            id=spec.id,
            title=spec.title,
            kind=spec.kind,
            status="passed",
            target=self._target_label(spec),
            observations=observations,
            artifacts=artifacts,
        )

    def _snapshot(self, pid: int, window_id: int, screenshot_path: Path) -> dict:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        code, stdout, stderr = self.transport.run(
            "get_window_state",
            {"pid": pid, "window_id": window_id, "screenshot_out_file": str(screenshot_path)},
            timeout=30,
        )
        if code:
            raise RuntimeError(stderr or stdout or "get_window_state failed")
        return self._json(stdout)

    def _action(self, tool: str, payload: dict) -> None:
        code, stdout, stderr = self.transport.run(tool, payload, timeout=20)
        if code:
            raise RuntimeError(stderr or stdout or f"{tool} failed")

    def _launch_payload(self, spec: UITestSpec) -> dict:
        if spec.kind == "web":
            if not spec.target.url:
                raise ValueError("web UI test requires target.url")
            return {"bundle_id": spec.target.chrome_bundle_id, "urls": [spec.target.url]}
        if spec.target.bundle_id:
            return {"bundle_id": spec.target.bundle_id}
        if spec.target.app_name:
            return {"name": spec.target.app_name}
        raise ValueError("native UI test requires target.bundle_id or target.app_name")

    def _target_label(self, spec: UITestSpec) -> str:
        if spec.kind == "web":
            return spec.target.url or ""
        return spec.target.bundle_id or spec.target.app_name or ""

    def _skipped_result(self, spec: UITestSpec, warning: str) -> UITestResult:
        return UITestResult(
            id=spec.id,
            title=spec.title,
            kind=spec.kind,
            status="warning",
            target=self._target_label(spec),
            error=warning,
        )

    def _find_element_index(self, tree: str, text: str) -> int | None:
        if not text:
            return None
        for line in tree.splitlines():
            if text in line:
                match = re.search(r"\[(\d+)\]", line)
                if match:
                    return int(match.group(1))
        return None

    def _artifact_path(self, docs_root: Path, path: Path) -> str:
        try:
            return path.relative_to(docs_root).as_posix()
        except ValueError:
            return path.name

    def _json(self, stdout: str) -> dict:
        text = stdout.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end < start:
                raise
            payload = json.loads(text[start : end + 1])
        return payload if isinstance(payload, dict) else {}
