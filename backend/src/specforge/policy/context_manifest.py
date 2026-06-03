from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Protocol

from ..core.contracts import ContextManifestEntry


CONTEXT_DIR = "context"
FOR_CODER = f"{CONTEXT_DIR}/for_coder.jsonl"
FOR_TESTER = f"{CONTEXT_DIR}/for_tester.jsonl"
RUNTIME_NOTES = f"{CONTEXT_DIR}/runtime_notes.jsonl"
Freshness = Literal["fresh", "changed", "missing-summary", "missing", "unknown"]


@dataclass(frozen=True)
class ManifestLine:
    file: str
    reason: str
    summary: str = ""
    symbols: list[str] | None = None
    public_api: list[str] | None = None
    risks: list[str] | None = None
    sha256: str | None = None
    last_scanned_at: str | None = None
    freshness: Freshness | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"file": self.file, "reason": self.reason}
        if self.summary:
            payload["summary"] = self.summary
        if self.symbols:
            payload["symbols"] = self.symbols
        if self.public_api:
            payload["public_api"] = self.public_api
        if self.risks:
            payload["risks"] = self.risks
        if self.sha256:
            payload["sha256"] = self.sha256
        if self.last_scanned_at:
            payload["last_scanned_at"] = self.last_scanned_at
        if self.freshness:
            payload["freshness"] = self.freshness
        return payload


class _ManifestSource(Protocol):
    context_for_coder: list[ContextManifestEntry]
    context_for_tester: list[ContextManifestEntry]


def _entries_to_lines(entries: Iterable[ContextManifestEntry | ManifestLine]) -> list[ManifestLine]:
    lines: list[ManifestLine] = []
    for entry in entries:
        if isinstance(entry, ContextManifestEntry):
            lines.append(
                ManifestLine(
                    file=entry.file,
                    reason=entry.reason,
                    summary=entry.summary,
                    symbols=entry.symbols,
                    public_api=entry.public_api,
                    risks=entry.risks,
                    sha256=entry.sha256,
                    last_scanned_at=entry.last_scanned_at,
                    freshness=_freshness_or_none(entry.freshness),
                )
            )
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
        merged[line.file] = merge_manifest_line(merged.get(line.file), line)
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
            lines.append(
                ManifestLine(
                    file=str(payload["file"]),
                    reason=str(payload.get("reason") or ""),
                    summary=str(payload.get("summary") or ""),
                    symbols=_string_list(payload.get("symbols")),
                    public_api=_string_list(payload.get("public_api")),
                    risks=_string_list(payload.get("risks")),
                    sha256=_optional_string(payload.get("sha256")),
                    last_scanned_at=_optional_string(payload.get("last_scanned_at")),
                    freshness=_freshness_or_none(payload.get("freshness")),
                )
            )
    return lines


def merge_manifest_line(existing: ManifestLine | None, incoming: ManifestLine) -> ManifestLine:
    if existing is None:
        return incoming
    return ManifestLine(
        file=incoming.file,
        reason=incoming.reason or existing.reason,
        summary=incoming.summary or existing.summary,
        symbols=incoming.symbols or existing.symbols,
        public_api=incoming.public_api or existing.public_api,
        risks=incoming.risks or existing.risks,
        sha256=incoming.sha256 or existing.sha256,
        last_scanned_at=incoming.last_scanned_at or existing.last_scanned_at,
        freshness=incoming.freshness or existing.freshness,
    )


def append_runtime_note(path: Path, *, note: str, node: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"note": note.strip(), "node": node}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def format_manifest_for_prompt(lines: Iterable[ManifestLine], *, heading: str) -> str:
    items = list(lines)
    if not items:
        return ""
    body = "\n".join(_format_manifest_line(line) for line in items)
    guidance = (
        "Use this manifest as the first-pass context package. Prefer the summaries and approved planning docs first. "
        "Open source files only when the summary is missing/stale, you need to edit that file, or a test/build failure requires deeper inspection. "
        "If you inspect paths outside this manifest, explain the reason in your final artifact summary."
    )
    return f"{heading}\n{guidance}\n{body}\n"


def _format_manifest_line(line: ManifestLine) -> str:
    parts = [
        f"- file: {line.file}",
        f"  reason: {line.reason or '(none provided)'}",
        f"  freshness: {line.freshness or 'unknown'}",
        f"  summary: {line.summary or '(missing; inspect the file only if needed for the task)'}",
    ]
    if line.public_api:
        parts.append(f"  public_api: {', '.join(line.public_api)}")
    if line.symbols:
        parts.append(f"  symbols: {', '.join(line.symbols)}")
    if line.risks:
        parts.append(f"  risks: {'; '.join(line.risks)}")
    if line.sha256:
        parts.append(f"  sha256: {line.sha256}")
    if line.last_scanned_at:
        parts.append(f"  last_scanned_at: {line.last_scanned_at}")
    return "\n".join(parts)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _freshness_or_none(value: object) -> Freshness | None:
    text = _optional_string(value)
    if text in {"fresh", "changed", "missing-summary", "missing", "unknown"}:
        return text  # type: ignore[return-value]
    return None


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
