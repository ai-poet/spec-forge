from __future__ import annotations

from pathlib import Path

import pytest

from specforge.context_manifest import append_manifest_lines, read_jsonl, resolve_coder_manifest, resolve_tester_manifest, write_jsonl
from specforge.context_manifest import ManifestLine
from specforge.contracts import ContextManifestEntry, PrdPlannerArtifact


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


def test_append_manifest_lines_merges(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    write_jsonl(target, [ManifestLine(file="prd.md", reason="base")])
    append_manifest_lines(target, [ManifestLine(file="testing_plan.md", reason="tests")])
    read_back = read_jsonl(target)
    assert {line.file for line in read_back} == {"prd.md", "testing_plan.md"}


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
