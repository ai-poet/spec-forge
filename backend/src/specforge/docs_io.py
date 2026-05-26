from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


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

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, relative_path: str) -> str:
        return (self.root / relative_path).read_text(encoding="utf-8")

