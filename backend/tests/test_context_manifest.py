from __future__ import annotations

from pathlib import Path

import pytest

from specforge.policy.context_manifest import (
    append_manifest_lines,
    format_manifest_for_prompt,
    read_jsonl,
    resolve_coder_manifest,
    resolve_tester_manifest,
    write_jsonl,
)
from specforge.policy.context_manifest import ManifestLine
from specforge.core.contracts import ContextManifestEntry, PrdPlannerArtifact


def test_write_and_read_jsonl(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    lines = resolve_coder_manifest(
        PrdPlannerArtifact(
            prd="prd body",
            context_for_coder=[ContextManifestEntry(file="prd.md", reason="design")],
            context_for_tester=[ContextManifestEntry(file="prd.md", reason="design")],
        )
    )
    write_jsonl(target, lines)
    read_back = read_jsonl(target)
    assert read_back[0].file == "prd.md"


def test_read_legacy_manifest_line_defaults_new_fields(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    target.write_text('{"file":"src/app.py","reason":"implementation"}\n', encoding="utf-8")

    line = read_jsonl(target)[0]

    assert line.file == "src/app.py"
    assert line.reason == "implementation"
    assert line.summary == ""
    assert line.symbols == []
    assert line.public_api == []
    assert line.risks == []
    assert line.sha256 is None
    assert line.last_scanned_at is None
    assert line.freshness is None


def test_write_and_read_enriched_manifest_line(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    write_jsonl(
        target,
        [
            ManifestLine(
                file="src/app.py",
                reason="implementation",
                summary="Application entry point.",
                symbols=["main"],
                public_api=["main"],
                risks=["Startup behavior"],
                sha256="abc123",
                last_scanned_at="2026-06-03T00:00:00Z",
                freshness="fresh",
            )
        ],
    )

    line = read_jsonl(target)[0]

    assert line.summary == "Application entry point."
    assert line.symbols == ["main"]
    assert line.public_api == ["main"]
    assert line.risks == ["Startup behavior"]
    assert line.sha256 == "abc123"
    assert line.last_scanned_at == "2026-06-03T00:00:00Z"
    assert line.freshness == "fresh"


def test_append_manifest_lines_merges(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    write_jsonl(target, [ManifestLine(file="prd.md", reason="base")])
    append_manifest_lines(target, [ManifestLine(file="testing_plan.md", reason="tests")])
    read_back = read_jsonl(target)
    assert {line.file for line in read_back} == {"prd.md", "testing_plan.md"}


def test_append_manifest_lines_preserves_cached_metadata(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    write_jsonl(
        target,
        [
            ManifestLine(
                file="prd.md",
                reason="base",
                summary="Existing PRD summary",
                sha256="abc123",
                freshness="fresh",
            )
        ],
    )

    append_manifest_lines(target, [ManifestLine(file="prd.md", reason="updated reason")])

    line = read_jsonl(target)[0]
    assert line.reason == "updated reason"
    assert line.summary == "Existing PRD summary"
    assert line.sha256 == "abc123"
    assert line.freshness == "fresh"


def test_format_manifest_for_prompt_includes_cache_guidance() -> None:
    text = format_manifest_for_prompt(
        [
            ManifestLine(
                file="src/app.py",
                reason="implementation",
                summary="Application entry point.",
                public_api=["main"],
                sha256="abc123",
                freshness="fresh",
            )
        ],
        heading="Required context files:",
    )

    assert "first-pass context package" in text
    assert "freshness: fresh" in text
    assert "summary: Application entry point." in text
    assert "public_api: main" in text
    assert "sha256: abc123" in text
    assert "outside this manifest" in text


def test_resolve_coder_manifest_requires_planner_entries() -> None:
    artifact = PrdPlannerArtifact(prd="a")
    with pytest.raises(ValueError, match="context_for_coder"):
        resolve_coder_manifest(artifact)


def test_resolve_tester_manifest_requires_planner_entries() -> None:
    artifact = PrdPlannerArtifact(
        prd="a",
        context_for_coder=[ContextManifestEntry(file="prd.md", reason="design")],
    )
    with pytest.raises(ValueError, match="context_for_tester"):
        resolve_tester_manifest(artifact)
