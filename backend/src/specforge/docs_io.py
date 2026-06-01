from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable


def checksum(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_paths(paths: Iterable[Path]) -> str:
    digest = sha256()
    for path in sorted(paths):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(checksum(path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def protected_test_files(root: Path) -> list[Path]:
    tests_root = root / "tests"
    if not tests_root.exists():
        return []
    files: list[Path] = []
    for path in tests_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[:2] == ("tests", "adversarial"):
            continue
        if len(relative.parts) >= 3 and relative.parts[:3] == ("tests", "ui", "recordings"):
            continue
        files.append(path)
    return sorted(files)


def test_integrity_manifest(root: Path) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in protected_test_files(root):
        relative = path.relative_to(root).as_posix()
        manifest[relative] = {"sha256": checksum(path), "size": path.stat().st_size}
    return manifest


def compare_test_integrity(root: Path, baseline: dict[str, dict[str, Any]]) -> list[str]:
    current = test_integrity_manifest(root)
    problems: list[str] = []
    for path, expected in baseline.items():
        actual = current.get(path)
        if actual is None:
            problems.append(f"missing protected test: {path}")
            continue
        if actual["sha256"] != expected["sha256"]:
            problems.append(f"modified protected test: {path}")
    for path in sorted(set(current) - set(baseline)):
        problems.append(f"new protected test outside planner baseline: {path}")
    return problems


@dataclass
class IterationDocs:
    root: Path

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "tests").mkdir(exist_ok=True)
        (self.root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
        (self.root / "tests" / "integration").mkdir(parents=True, exist_ok=True)
        (self.root / "tests" / "ui").mkdir(parents=True, exist_ok=True)
        (self.root / "tests" / "adversarial").mkdir(parents=True, exist_ok=True)
        (self.root / "clarifications").mkdir(parents=True, exist_ok=True)
        (self.root / "context").mkdir(parents=True, exist_ok=True)

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.root / safe_relative_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, relative_path: str) -> str:
        return (self.root / safe_relative_path(relative_path)).read_text(encoding="utf-8")
