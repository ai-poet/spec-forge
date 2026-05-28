from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
from queue import Queue
from threading import Thread
from pathlib import Path
from typing import Callable, Optional


@dataclass
class CLIResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class BaseRunner:
    def run(self, command: list[str], cwd: Optional[Path] = None, on_output: Optional[Callable[[str, str], None]] = None) -> CLIResult:
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            if on_output and proc.stdout:
                on_output("stdout", proc.stdout)
            if on_output and proc.stderr:
                on_output("stderr", proc.stderr)
            return CLIResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc))


class DryRunRunner(BaseRunner):
    def run(self, command: list[str], cwd: Optional[Path] = None, on_output: Optional[Callable[[str, str], None]] = None) -> CLIResult:
        payload = {"command": command, "cwd": str(cwd) if cwd else None, "mode": "dry-run"}
        stdout = json.dumps(payload, indent=2)
        if on_output:
            on_output("stdout", stdout)
        return CLIResult(command=command, returncode=0, stdout=stdout, stderr="")


class RealCLIRunner(BaseRunner):
    def run(self, command: list[str], cwd: Optional[Path] = None, on_output: Optional[Callable[[str, str], None]] = None) -> CLIResult:
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc))

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
        for thread in threads:
            thread.join(timeout=0.1)
        return CLIResult(command=command, returncode=proc.returncode or 0, stdout="".join(stdout_parts), stderr="".join(stderr_parts))
