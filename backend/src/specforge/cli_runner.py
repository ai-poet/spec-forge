from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
from pathlib import Path
from typing import Optional


@dataclass
class CLIResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class BaseRunner:
    def run(self, command: list[str], cwd: Optional[Path] = None) -> CLIResult:
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            return CLIResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except FileNotFoundError as exc:
            return CLIResult(command=command, returncode=127, stdout="", stderr=str(exc))


class DryRunRunner(BaseRunner):
    def run(self, command: list[str], cwd: Optional[Path] = None) -> CLIResult:
        payload = {"command": command, "cwd": str(cwd) if cwd else None, "mode": "dry-run"}
        return CLIResult(command=command, returncode=0, stdout=json.dumps(payload, indent=2), stderr="")


class RealCLIRunner(BaseRunner):
    pass
