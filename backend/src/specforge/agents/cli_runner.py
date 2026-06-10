from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timed_out: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    stdout_byte_count: int | None = None
    stderr_byte_count: int | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))

    @property
    def stdout_bytes(self) -> int:
        if self.stdout_byte_count is not None:
            return self.stdout_byte_count
        return len((self.stdout or "").encode("utf-8"))

    @property
    def stderr_bytes(self) -> int:
        if self.stderr_byte_count is not None:
            return self.stderr_byte_count
        return len((self.stderr or "").encode("utf-8"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BoundedTextBuffer:
    def __init__(self, max_chars: int | None) -> None:
        self.max_chars = max_chars if max_chars and max_chars > 0 else None
        self._parts: list[str] = []
        self._chars = 0
        self.byte_count = 0
        self.truncated = False

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self.byte_count += len(chunk.encode("utf-8"))
        self._parts.append(chunk)
        self._chars += len(chunk)
        self._trim()

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def _trim(self) -> None:
        if self.max_chars is None:
            return
        overflow = self._chars - self.max_chars
        if overflow <= 0:
            return
        self.truncated = True
        while self._parts and overflow > 0:
            first = self._parts[0]
            if len(first) <= overflow:
                self._parts.pop(0)
                self._chars -= len(first)
                overflow -= len(first)
                continue
            self._parts[0] = first[overflow:]
            self._chars -= overflow
            overflow = 0


_DEFAULT_CAPTURE_MAX_CHARS = int(os.getenv("SPECFORGE_CLI_RESULT_MAX_CHARS", str(512 * 1024)) or str(512 * 1024))


class BaseRunner:
    def run(
        self,
        command: list[str],
        cwd: Optional[Path] = None,
        on_output: Optional[Callable[[str, str], None]] = None,
        *,
        iteration_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        capture_max_chars: Optional[int] = _DEFAULT_CAPTURE_MAX_CHARS,
        stdin_text: Optional[str] = None,
    ) -> CLIResult:
        started_at = _utcnow()
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds, input=stdin_text)
            finished_at = _utcnow()
            if on_output and proc.stdout:
                on_output("stdout", proc.stdout)
            if on_output and proc.stderr:
                on_output("stderr", proc.stderr)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            stdout_tail = stdout[-capture_max_chars:] if capture_max_chars and len(stdout) > capture_max_chars else stdout
            stderr_tail = stderr[-capture_max_chars:] if capture_max_chars and len(stderr) > capture_max_chars else stderr
            return CLIResult(
                command=command,
                returncode=proc.returncode,
                stdout=stdout_tail,
                stderr=stderr_tail,
                started_at=started_at,
                finished_at=finished_at,
                metadata={"stdout_truncated": stdout_tail != stdout, "stderr_truncated": stderr_tail != stderr},
                stdout_byte_count=len(stdout.encode("utf-8")),
                stderr_byte_count=len(stderr.encode("utf-8")),
            )
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc), started_at=started_at, finished_at=_utcnow())
        except OSError as exc:
            return CLIResult(command=command, returncode=126, stdout="", stderr=str(exc), started_at=started_at, finished_at=_utcnow())
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
            return CLIResult(command=command, returncode=124, stdout=stdout, stderr=stderr or f"CLI timed out after {timeout_seconds}s", started_at=started_at, finished_at=_utcnow(), timed_out=True)

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
        timeout_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        capture_max_chars: Optional[int] = _DEFAULT_CAPTURE_MAX_CHARS,
        stdin_text: Optional[str] = None,
    ) -> CLIResult:
        started_at = _utcnow()
        payload = {"command": command, "cwd": str(cwd) if cwd else None, "mode": "dry-run"}
        if stdin_text is not None:
            payload["stdin_bytes"] = len(stdin_text.encode("utf-8"))
        stdout = json.dumps(payload, indent=2)
        if on_output:
            on_output("stdout", stdout)
        return CLIResult(command=command, returncode=0, stdout=stdout, stderr="", started_at=started_at, finished_at=_utcnow())


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
        timeout_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        capture_max_chars: Optional[int] = _DEFAULT_CAPTURE_MAX_CHARS,
        stdin_text: Optional[str] = None,
    ) -> CLIResult:
        started_at = _utcnow()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc), started_at=started_at, finished_at=_utcnow())
        except OSError as exc:
            return CLIResult(command=command, returncode=126, stdout="", stderr=str(exc), started_at=started_at, finished_at=_utcnow())

        stdin_thread: Thread | None = None
        if stdin_text is not None:
            def write_stdin() -> None:
                try:
                    if proc.stdin:
                        proc.stdin.write(stdin_text)
                        proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            stdin_thread = Thread(target=write_stdin, daemon=True)
            stdin_thread.start()

        if iteration_id:
            with self._lock:
                self._active[iteration_id] = proc
                self._write_registry_entry(iteration_id, proc, command, cwd)

        stdout_buffer = BoundedTextBuffer(capture_max_chars)
        stderr_buffer = BoundedTextBuffer(capture_max_chars)
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
            deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
            idle_deadline = time.monotonic() + idle_timeout_seconds if idle_timeout_seconds else None
            timed_out = False
            idle_timed_out = False
            while proc.poll() is None or any(thread.is_alive() for thread in threads) or not queue.empty():
                if deadline is not None and proc.poll() is None and time.monotonic() > deadline:
                    timed_out = True
                    self._terminate_process(proc)
                if idle_deadline is not None and proc.poll() is None and time.monotonic() > idle_deadline:
                    idle_timed_out = True
                    self._terminate_process(proc)
                while not queue.empty():
                    name, chunk = queue.get()
                    if idle_timeout_seconds:
                        idle_deadline = time.monotonic() + idle_timeout_seconds
                    if name == "stdout":
                        stdout_buffer.append(chunk)
                    else:
                        stderr_buffer.append(chunk)
                    if on_output:
                        on_output(name, chunk)
                for thread in threads:
                    thread.join(timeout=0.01)
        finally:
            if stdin_thread is not None:
                stdin_thread.join(timeout=0.5)
            for thread in threads:
                thread.join(timeout=0.1)
            if iteration_id:
                with self._lock:
                    self._active.pop(iteration_id, None)
                    self._remove_registry_entry(iteration_id)

        returncode = proc.returncode if proc.returncode is not None else proc.wait()
        stdout = stdout_buffer.text
        stderr = stderr_buffer.text
        if timed_out and "timed out" not in stderr.lower():
            stderr = f"{stderr}\nCLI timed out after {timeout_seconds}s".strip()
        if idle_timed_out and "idle timed out" not in stderr.lower():
            stderr = f"{stderr}\nCLI idle timed out after {idle_timeout_seconds}s".strip()
        metadata = {"stdout_truncated": stdout_buffer.truncated, "stderr_truncated": stderr_buffer.truncated}
        return CLIResult(
            command=command,
            returncode=124 if timed_out or idle_timed_out else returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            finished_at=_utcnow(),
            timed_out=timed_out or idle_timed_out,
            metadata=metadata,
            stdout_byte_count=stdout_buffer.byte_count,
            stderr_byte_count=stderr_buffer.byte_count,
        )

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
