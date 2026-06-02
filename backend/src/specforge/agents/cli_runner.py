from __future__ import annotations

from dataclasses import dataclass
import json
import os
import signal
import subprocess
import time
from queue import Queue
from threading import Lock, Thread
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CLIResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class BaseRunner:
    def run(
        self,
        command: list[str],
        cwd: Optional[Path] = None,
        on_output: Optional[Callable[[str, str], None]] = None,
        *,
        iteration_id: Optional[str] = None,
    ) -> CLIResult:
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            if on_output and proc.stdout:
                on_output("stdout", proc.stdout)
            if on_output and proc.stderr:
                on_output("stderr", proc.stderr)
            return CLIResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc))

    def cancel(self, iteration_id: str) -> bool:
        return False


class DryRunRunner(BaseRunner):
    def run(
        self,
        command: list[str],
        cwd: Optional[Path] = None,
        on_output: Optional[Callable[[str, str], None]] = None,
        *,
        iteration_id: Optional[str] = None,
    ) -> CLIResult:
        payload = {"command": command, "cwd": str(cwd) if cwd else None, "mode": "dry-run"}
        stdout = json.dumps(payload, indent=2)
        if on_output:
            on_output("stdout", stdout)
        return CLIResult(command=command, returncode=0, stdout=stdout, stderr="")


class RealCLIRunner(BaseRunner):
    def __init__(self, *, registry_path: Optional[Path] = None) -> None:
        self._lock = Lock()
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._registry_path = registry_path

    def run(
        self,
        command: list[str],
        cwd: Optional[Path] = None,
        on_output: Optional[Callable[[str, str], None]] = None,
        *,
        iteration_id: Optional[str] = None,
    ) -> CLIResult:
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc))

        if iteration_id:
            with self._lock:
                self._active[iteration_id] = proc
                self._write_registry_entry(iteration_id, proc, command, cwd)

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        queue: Queue[tuple[str, str]] = Queue()

        def read_stream(name: str, stream) -> None:
            try:
                for line in iter(stream.readline, ""):
                    queue.put((name, line))
            finally:
                stream.close()

        threads = [
            Thread(target=read_stream, args=("stdout", proc.stdout), daemon=True),
            Thread(target=read_stream, args=("stderr", proc.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            while proc.poll() is None or any(thread.is_alive() for thread in threads) or not queue.empty():
                while not queue.empty():
                    name, chunk = queue.get()
                    if name == "stdout":
                        stdout_parts.append(chunk)
                    else:
                        stderr_parts.append(chunk)
                    if on_output:
                        on_output(name, chunk)
                for thread in threads:
                    thread.join(timeout=0.01)
        finally:
            for thread in threads:
                thread.join(timeout=0.1)
            if iteration_id:
                with self._lock:
                    self._active.pop(iteration_id, None)
                    self._remove_registry_entry(iteration_id)

        returncode = proc.returncode if proc.returncode is not None else proc.wait()
        return CLIResult(command=command, returncode=returncode, stdout="".join(stdout_parts), stderr="".join(stderr_parts))

    def cancel(self, iteration_id: str) -> bool:
        with self._lock:
            proc = self._active.get(iteration_id)
        if proc is None or proc.poll() is not None:
            return False
        self._terminate_process(proc)
        with self._lock:
            self._active.pop(iteration_id, None)
            self._remove_registry_entry(iteration_id)
        return True

    def cancel_all(self) -> list[str]:
        with self._lock:
            active = dict(self._active)
        cancelled: list[str] = []
        for iteration_id, proc in active.items():
            if proc.poll() is None:
                self._terminate_process(proc)
                cancelled.append(iteration_id)
        if cancelled:
            with self._lock:
                for iteration_id in cancelled:
                    self._active.pop(iteration_id, None)
                    self._remove_registry_entry(iteration_id)
        return cancelled

    def cleanup_registry_processes(self) -> list[str]:
        entries = self._read_registry()
        cleaned: list[str] = []
        for iteration_id, entry in entries.items():
            pid = self._entry_int(entry, "pid")
            pgid = self._entry_int(entry, "pgid")
            if pid is None:
                cleaned.append(iteration_id)
                continue
            if not self._pid_running(pid):
                cleaned.append(iteration_id)
                continue
            if pgid is not None and hasattr(os, "getpgid"):
                try:
                    if os.getpgid(pid) != pgid:
                        cleaned.append(iteration_id)
                        continue
                except ProcessLookupError:
                    cleaned.append(iteration_id)
                    continue
            self._terminate_pid(pid, pgid)
            cleaned.append(iteration_id)
        if cleaned:
            with self._lock:
                current = self._read_registry()
                for iteration_id in cleaned:
                    current.pop(iteration_id, None)
                self._write_registry(current)
        return cleaned

    def _terminate_process(self, proc: subprocess.Popen[str]) -> None:
        pgid: int | None = None
        try:
            if hasattr(os, "killpg"):
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                if hasattr(os, "killpg"):
                    os.killpg(pgid if pgid is not None else os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _terminate_pid(self, pid: int, pgid: Optional[int]) -> None:
        try:
            if hasattr(os, "killpg") and pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not self._pid_running(pid):
                return
            time.sleep(0.05)
        try:
            if hasattr(os, "killpg") and pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _write_registry_entry(self, iteration_id: str, proc: subprocess.Popen[str], command: list[str], cwd: Optional[Path]) -> None:
        if self._registry_path is None:
            return
        entries = self._read_registry()
        try:
            pgid = os.getpgid(proc.pid) if hasattr(os, "getpgid") else None
        except ProcessLookupError:
            pgid = None
        entries[iteration_id] = {
            "pid": proc.pid,
            "pgid": pgid,
            "command": command,
            "cwd": str(cwd) if cwd else None,
            "started_at": time.time(),
        }
        self._write_registry(entries)

    def _remove_registry_entry(self, iteration_id: str) -> None:
        if self._registry_path is None:
            return
        entries = self._read_registry()
        if iteration_id not in entries:
            return
        entries.pop(iteration_id, None)
        self._write_registry(entries)

    def _read_registry(self) -> dict[str, dict[str, Any]]:
        if self._registry_path is None or not self._registry_path.exists():
            return {}
        try:
            raw = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}

    def _write_registry(self, entries: dict[str, dict[str, Any]]) -> None:
        if self._registry_path is None:
            return
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not entries:
            try:
                self._registry_path.unlink()
            except FileNotFoundError:
                pass
            return
        temp_path = self._registry_path.with_suffix(f"{self._registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._registry_path)

    @staticmethod
    def _entry_int(entry: dict[str, Any], key: str) -> Optional[int]:
        value = entry.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if proc.returncode != 0:
                return False
            if proc.stdout.strip().startswith("Z"):
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return True
