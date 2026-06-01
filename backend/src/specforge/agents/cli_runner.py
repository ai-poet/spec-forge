from __future__ import annotations

from dataclasses import dataclass
import json
import os
import signal
import subprocess
from queue import Queue
from threading import Lock, Thread
from pathlib import Path
from typing import Callable, Optional


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
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[str, subprocess.Popen[str]] = {}

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

        returncode = proc.returncode if proc.returncode is not None else proc.wait()
        return CLIResult(command=command, returncode=returncode, stdout="".join(stdout_parts), stderr="".join(stderr_parts))

    def cancel(self, iteration_id: str) -> bool:
        with self._lock:
            proc = self._active.get(iteration_id)
        if proc is None or proc.poll() is not None:
            return False
        self._terminate_process(proc)
        return True

    def _terminate_process(self, proc: subprocess.Popen[str]) -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
