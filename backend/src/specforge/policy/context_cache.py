from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..documents.docs_io import checksum, safe_relative_path
from .context_manifest import ManifestLine, merge_manifest_line, read_jsonl, write_jsonl


CONTEXT_INDEX = ".specforge/context_index.jsonl"
PLANNER_CONTEXT_MAX_ENTRIES = 25
PLANNER_CONTEXT_MAX_CHARS = 6000
_PLANNING_DOCS = {"prd.md", "testing_plan.md", "verify_report.md", "ui_report.md", "delivery_advice.md"}
_STABLE_PROJECT_DOCS = (
    "docs/00_convention.md",
    "docs/01_project_goal.md",
    "docs/spec-index.md",
)
_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}


def enrich_manifest_lines(repo_root: Path, docs_root: Path, lines: Iterable[ManifestLine]) -> list[ManifestLine]:
    """Attach hash/freshness metadata and reusable context summaries to manifest lines."""
    index_path = repo_root / CONTEXT_INDEX
    cached = {line.file: line for line in read_jsonl(index_path)}
    enriched: list[ManifestLine] = []

    for line in lines:
        enriched_line, cache_key, cache_line = _enrich_line(repo_root, docs_root, line, cached)
        enriched.append(enriched_line)
        if cache_key and cache_line:
            cached[cache_key] = cache_line

    write_jsonl(index_path, [cached[key] for key in sorted(cached)])
    return enriched


def format_planner_context(
    repo_root: Path,
    *,
    max_entries: int = PLANNER_CONTEXT_MAX_ENTRIES,
    max_chars: int = PLANNER_CONTEXT_MAX_CHARS,
) -> str:
    """Return a bounded project context package for planning-stage prompts."""
    lines = _planner_context_lines(repo_root)
    if not lines:
        return (
            "## Planner project context cache\n"
            "No cached project context yet. Use project docs first, then inspect only the files needed to produce this planning artifact.\n"
        )

    ordered = sorted(lines, key=_planner_line_sort_key)[:max_entries]
    heading = (
        "## Planner project context cache\n"
        "Use this cached project context before broad repository discovery. Treat `fresh` summaries as reusable facts. "
        "Inspect source only when entries are `changed`, `missing-summary`, `missing`, too vague, or directly needed for this planning artifact. "
        "If you inspect paths outside this cache, include those paths in context manifests with reasons.\n"
    )
    body_lines: list[str] = []
    for line in ordered:
        body_lines.append(_format_planner_context_line(line))
    body = "\n".join(body_lines)
    text = f"{heading}{body}\n"
    if len(text) <= max_chars:
        return text
    suffix = "\n... [planner context truncated]\n"
    return text[: max(0, max_chars - len(suffix))].rstrip() + suffix


def _planner_context_lines(repo_root: Path) -> list[ManifestLine]:
    lines: list[ManifestLine] = []
    for relative_path in _STABLE_PROJECT_DOCS:
        path = repo_root / relative_path
        if not path.exists() or not path.is_file():
            continue
        lines.append(_line_for_existing_path(repo_root, path, relative_path, trusted_doc=True))

    index_lines = read_jsonl(repo_root / CONTEXT_INDEX)
    for line in index_lines:
        lines.append(_refresh_cached_line_for_planner(repo_root, line))
    return _dedupe_planner_lines(lines)


def _line_for_existing_path(repo_root: Path, path: Path, display_path: str, *, trusted_doc: bool) -> ManifestLine:
    current_sha = checksum(path)
    summary = _summarize_path(path, reason="Stable project planning document", trusted=trusted_doc)
    symbols = _extract_symbols(path)
    return ManifestLine(
        file=display_path,
        reason="Stable project planning document" if trusted_doc else "Cached project context",
        summary=summary,
        symbols=symbols,
        public_api=_public_symbols(symbols),
        sha256=current_sha,
        last_scanned_at=_now(),
        freshness="fresh" if summary else "missing-summary",
    )


def _refresh_cached_line_for_planner(repo_root: Path, line: ManifestLine) -> ManifestLine:
    try:
        relative = safe_relative_path(line.file)
    except ValueError:
        return ManifestLine(
            file=line.file,
            reason=line.reason,
            summary=line.summary,
            symbols=line.symbols,
            public_api=line.public_api,
            risks=line.risks,
            sha256=line.sha256,
            last_scanned_at=line.last_scanned_at,
            freshness="missing",
        )
    path = repo_root / relative
    if not path.exists() or not path.is_file():
        return ManifestLine(
            file=line.file,
            reason=line.reason,
            summary=line.summary,
            symbols=line.symbols,
            public_api=line.public_api,
            risks=line.risks,
            sha256=line.sha256,
            last_scanned_at=line.last_scanned_at,
            freshness="missing",
        )
    current_sha = checksum(path)
    if line.sha256 == current_sha and line.summary and line.freshness != "changed":
        return ManifestLine(
            file=line.file,
            reason=line.reason,
            summary=line.summary,
            symbols=line.symbols,
            public_api=line.public_api,
            risks=line.risks,
            sha256=current_sha,
            last_scanned_at=_now(),
            freshness="fresh",
        )
    if line.sha256 and line.sha256 != current_sha:
        return ManifestLine(
            file=line.file,
            reason=line.reason,
            summary=line.summary,
            symbols=_extract_symbols(path) or line.symbols,
            public_api=_public_symbols(_extract_symbols(path)) or line.public_api,
            risks=line.risks,
            sha256=current_sha,
            last_scanned_at=_now(),
            freshness="changed",
        )
    summary = line.summary or _summarize_path(path, reason=line.reason, trusted=_is_project_doc_path(line.file))
    freshness = "fresh" if summary and line.sha256 == current_sha else "missing-summary"
    return ManifestLine(
        file=line.file,
        reason=line.reason,
        summary=summary,
        symbols=line.symbols or _extract_symbols(path),
        public_api=line.public_api or _public_symbols(line.symbols or _extract_symbols(path)),
        risks=line.risks,
        sha256=current_sha,
        last_scanned_at=_now(),
        freshness=freshness,
    )


def _dedupe_planner_lines(lines: Iterable[ManifestLine]) -> list[ManifestLine]:
    merged: dict[str, ManifestLine] = {}
    for line in lines:
        existing = merged.get(line.file)
        if existing is None:
            merged[line.file] = line
            continue
        merged[line.file] = _prefer_planner_line(existing, line)
    return list(merged.values())


def _prefer_planner_line(left: ManifestLine, right: ManifestLine) -> ManifestLine:
    if _freshness_rank(right.freshness) > _freshness_rank(left.freshness):
        return right
    if _freshness_rank(right.freshness) == _freshness_rank(left.freshness) and len(right.summary) > len(left.summary):
        return right
    return left


def _planner_line_sort_key(line: ManifestLine) -> tuple[int, int, str]:
    project_doc_rank = 0 if line.file in _STABLE_PROJECT_DOCS else 1
    return (project_doc_rank, -_freshness_rank(line.freshness), line.file)


def _freshness_rank(value: str | None) -> int:
    return {
        "fresh": 4,
        "missing-summary": 3,
        "changed": 2,
        "missing": 1,
    }.get(value or "unknown", 0)


def _format_planner_context_line(line: ManifestLine) -> str:
    parts = [
        f"- file: {line.file}",
        f"  freshness: {line.freshness or 'unknown'}",
        f"  summary: {line.summary or '(no cached summary; inspect only if needed)'}",
    ]
    if line.reason:
        parts.append(f"  reason: {line.reason}")
    if line.public_api:
        parts.append(f"  public_api: {', '.join(line.public_api[:8])}")
    if line.symbols:
        parts.append(f"  symbols: {', '.join(line.symbols[:8])}")
    if line.sha256:
        parts.append(f"  sha256: {line.sha256}")
    return "\n".join(parts)


def _is_project_doc_path(value: str) -> bool:
    return value in _STABLE_PROJECT_DOCS or value.startswith("docs/")


def _enrich_line(
    repo_root: Path,
    docs_root: Path,
    line: ManifestLine,
    cached: dict[str, ManifestLine],
) -> tuple[ManifestLine, str | None, ManifestLine | None]:
    resolved = _resolve_manifest_path(repo_root, docs_root, line.file)
    cache_key = _cache_key(repo_root, resolved.path)
    if not resolved.path.exists() or not resolved.path.is_file():
        return (
            ManifestLine(
                file=line.file,
                reason=line.reason,
                summary=line.summary,
                symbols=line.symbols,
                public_api=line.public_api,
                risks=line.risks,
                sha256=line.sha256,
                last_scanned_at=line.last_scanned_at,
                freshness="missing",
            ),
            None,
            None,
        )

    current_sha = checksum(resolved.path)
    cached_line = cached.get(cache_key or line.file)
    same_cached_hash = bool(cached_line and cached_line.sha256 == current_sha)
    line_summary_matches_hash = bool(
        line.summary
        and line.freshness != "changed"
        and (line.sha256 is None or line.sha256 == current_sha)
    )
    generated_summary = _summarize_path(resolved.path, reason=line.reason, trusted=resolved.trusted_doc)
    summary = line.summary if line_summary_matches_hash else ""
    if not summary and same_cached_hash and cached_line:
        summary = cached_line.summary
    if not summary and resolved.trusted_doc:
        summary = generated_summary
    if not summary and cached_line and cached_line.sha256 != current_sha:
        summary = cached_line.summary

    use_cached_metadata = bool(cached_line and cached_line.sha256 == current_sha)
    symbols = line.symbols or (cached_line.symbols if use_cached_metadata and cached_line else None) or _extract_symbols(resolved.path)
    public_api = line.public_api or (cached_line.public_api if use_cached_metadata and cached_line else None) or _public_symbols(symbols)
    risks = line.risks or (cached_line.risks if use_cached_metadata and cached_line else None)
    freshness = _freshness(
        line=line,
        cached_line=cached_line,
        current_sha=current_sha,
        summary=summary,
        trusted_doc=resolved.trusted_doc,
        line_summary_matches_hash=line_summary_matches_hash,
    )
    scanned_at = _now()

    enriched = ManifestLine(
        file=line.file,
        reason=line.reason or (cached_line.reason if cached_line else ""),
        summary=summary,
        symbols=symbols,
        public_api=public_api,
        risks=risks,
        sha256=current_sha,
        last_scanned_at=scanned_at,
        freshness=freshness,
    )
    cache_entry = _cache_entry(
        cache_key=cache_key or line.file,
        current_sha=current_sha,
        scanned_at=scanned_at,
        freshness=freshness,
        enriched=enriched,
        cached_line=cached_line,
    )
    return enriched, cache_key, cache_entry


class _ResolvedPath:
    def __init__(self, path: Path, *, trusted_doc: bool) -> None:
        self.path = path
        self.trusted_doc = trusted_doc


def _resolve_manifest_path(repo_root: Path, docs_root: Path, value: str) -> _ResolvedPath:
    relative = safe_relative_path(value)
    docs_path = docs_root / relative
    if docs_path.exists():
        return _ResolvedPath(docs_path, trusted_doc=_is_trusted_doc(relative))
    repo_path = repo_root / relative
    return _ResolvedPath(repo_path, trusted_doc=False)


def _cache_key(repo_root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def _is_trusted_doc(relative: Path) -> bool:
    text = relative.as_posix()
    return text in _PLANNING_DOCS or text.startswith(("context/", "discovery/", "clarifications/"))


def _freshness(
    *,
    line: ManifestLine,
    cached_line: ManifestLine | None,
    current_sha: str,
    summary: str,
    trusted_doc: bool,
    line_summary_matches_hash: bool,
) -> str:
    if trusted_doc and summary:
        return "fresh"
    if line_summary_matches_hash or (
        cached_line
        and cached_line.freshness != "changed"
        and cached_line.sha256 == current_sha
        and summary
    ):
        return "fresh"
    if cached_line and cached_line.sha256 and cached_line.sha256 != current_sha:
        return "changed"
    return "missing-summary" if not summary else "fresh"


def _cache_entry(
    *,
    cache_key: str,
    current_sha: str,
    scanned_at: str,
    freshness: str,
    enriched: ManifestLine,
    cached_line: ManifestLine | None,
) -> ManifestLine:
    if freshness == "changed" and cached_line:
        return ManifestLine(
            file=cache_key,
            reason=enriched.reason or cached_line.reason,
            summary=cached_line.summary,
            symbols=cached_line.symbols or enriched.symbols,
            public_api=cached_line.public_api or enriched.public_api,
            risks=cached_line.risks or enriched.risks,
            sha256=cached_line.sha256,
            last_scanned_at=cached_line.last_scanned_at,
            freshness="changed",
        )
    entry = ManifestLine(
        file=cache_key,
        reason=enriched.reason,
        summary=enriched.summary,
        symbols=enriched.symbols,
        public_api=enriched.public_api,
        risks=enriched.risks,
        sha256=current_sha,
        last_scanned_at=scanned_at,
        freshness=freshness,
    )
    if not cached_line:
        return entry
    merged = merge_manifest_line(cached_line, entry)
    return ManifestLine(
        file=cache_key,
        reason=merged.reason,
        summary=enriched.summary or merged.summary,
        symbols=enriched.symbols or merged.symbols,
        public_api=enriched.public_api or merged.public_api,
        risks=enriched.risks or merged.risks,
        sha256=current_sha,
        last_scanned_at=scanned_at,
        freshness=freshness,
    )


def _summarize_path(path: Path, *, reason: str, trusted: bool) -> str:
    if path.suffix.lower() in {".md", ".markdown"}:
        return _summarize_markdown(path, reason=reason)
    if trusted:
        return reason
    return ""


def _summarize_markdown(path: Path, *, reason: str) -> str:
    text = _read_text_sample(path)
    lines = [line.strip() for line in text.splitlines()]
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), "")
    body = next((line for line in lines if line and not line.startswith("---") and not line.startswith("#") and ":" not in line[:24]), "")
    parts = []
    if title:
        parts.append(title)
    if body:
        parts.append(body)
    if not parts and reason:
        parts.append(reason)
    return " ".join(parts)[:500]


def _extract_symbols(path: Path) -> list[str]:
    if path.suffix.lower() not in _SOURCE_EXTENSIONS:
        return []
    text = _read_text_sample(path)
    patterns = [
        r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        r"^\s*export\s+(?:const|let|var|type|interface)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            name = match.group(1)
            if name not in found:
                found.append(name)
            if len(found) >= 12:
                return found
    return found


def _public_symbols(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return []
    return [symbol for symbol in symbols if not symbol.startswith("_")][:12]


def _read_text_sample(path: Path, limit: int = 24_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
