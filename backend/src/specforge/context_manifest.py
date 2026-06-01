from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from .contracts import ContextManifestEntry


CONTEXT_DIR = "context"
FOR_CODER = f"{CONTEXT_DIR}/for_coder.jsonl"
FOR_TESTER = f"{CONTEXT_DIR}/for_tester.jsonl"
RUNTIME_NOTES = f"{CONTEXT_DIR}/runtime_notes.jsonl"


@dataclass(frozen=True)
class ManifestLine:
    file: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"file": self.file, "reason": self.reason}


class _ManifestSource(Protocol):
    context_for_coder: list[ContextManifestEntry]
    context_for_tester: list[ContextManifestEntry]


def _entries_to_lines(entries: Iterable[ContextManifestEntry | ManifestLine]) -> list[ManifestLine]:
    lines: list[ManifestLine] = []
    for entry in entries:
        if isinstance(entry, ContextManifestEntry):
            lines.append(ManifestLine(file=entry.file, reason=entry.reason))
        else:
            lines.append(entry)
    return lines


def resolve_coder_manifest(artifact: _ManifestSource) -> list[ManifestLine]:
    if not artifact.context_for_coder:
        raise ValueError("PRD planner artifact must include non-empty context_for_coder")
    return _entries_to_lines(artifact.context_for_coder)


def resolve_tester_manifest(artifact: _ManifestSource) -> list[ManifestLine]:
    if not artifact.context_for_tester:
        raise ValueError("PRD planner artifact must include non-empty context_for_tester")
    return _entries_to_lines(artifact.context_for_tester)


def append_manifest_lines(path: Path, extra: Iterable[ManifestLine]) -> None:
    existing = read_jsonl(path)
    merged = {line.file: line for line in existing}
    for line in extra:
        merged[line.file] = line
    write_jsonl(path, merged.values())


def write_jsonl(path: Path, lines: Iterable[ManifestLine]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(line.to_dict(), ensure_ascii=False) for line in lines)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def read_jsonl(path: Path) -> list[ManifestLine]:
    if not path.exists():
        return []
    lines: list[ManifestLine] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("file"):
            lines.append(ManifestLine(file=str(payload["file"]), reason=str(payload.get("reason") or "")))
    return lines


def append_runtime_note(path: Path, *, note: str, node: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"note": note.strip(), "node": node}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def format_manifest_for_prompt(lines: Iterable[ManifestLine], *, heading: str) -> str:
    items = list(lines)
    if not items:
        return ""
    body = "\n".join(f"- {line.file}: {line.reason}" for line in items)
    return f"{heading}\n{body}\n"


def read_runtime_notes(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("note"):
            rows.append({"note": str(payload["note"]), "node": str(payload.get("node") or "")})
    return rows


def format_runtime_notes_section(path: Path) -> str:
    rows = read_runtime_notes(path)
    if not rows:
        return ""
    body = "\n".join(f"- [{row.get('node') or 'user'}] {row['note']}" for row in rows)
    return f"Human runtime notes (apply on next agent turn):\n{body}\n"
