from __future__ import annotations

from pathlib import Path

import pytest

from specforge.context_manifest import read_jsonl, resolve_coder_manifest, resolve_tester_manifest, write_jsonl
from specforge.contracts import ArtifactFile, ContextManifestEntry, PlannerArtifact


def test_write_and_read_jsonl(tmp_path: Path) -> None:
    target = tmp_path / "for_coder.jsonl"
    lines = resolve_coder_manifest(
        PlannerArtifact(
            system_design="a",
            modification_plan="b",
            testing_plan="c",
            context_for_coder=[ContextManifestEntry(file="system_design.md", reason="design")],
            context_for_tester=[ContextManifestEntry(file="system_design.md", reason="design")],
        )
    )
    write_jsonl(target, lines)
    read_back = read_jsonl(target)
    assert read_back[0].file == "system_design.md"


def test_resolve_coder_manifest_requires_planner_entries() -> None:
    artifact = PlannerArtifact(
        system_design="a",
        modification_plan="b",
        testing_plan="c",
        tests=[ArtifactFile(path="tests/unit/a.py", content="x")],
    )
    with pytest.raises(ValueError, match="context_for_coder"):
        resolve_coder_manifest(artifact)


def test_resolve_tester_manifest_requires_planner_entries() -> None:
    artifact = PlannerArtifact(
        system_design="a",
        modification_plan="b",
        testing_plan="c",
        context_for_coder=[ContextManifestEntry(file="system_design.md", reason="design")],
    )
    with pytest.raises(ValueError, match="context_for_tester"):
        resolve_tester_manifest(artifact)
