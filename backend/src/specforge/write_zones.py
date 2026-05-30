from __future__ import annotations

import re
from typing import Literal, Optional

from .contracts import Defect, TesterArtifact

WriteZoneOwner = Literal["coder", "tester", "planner"]
RetryTarget = Literal["coder", "tester", "blocked"]

TESTER_DOC_NAMES = frozenset(
    {
        "verify_report.md",
        "delivery_advice.md",
        "ui_report.md",
        "ui_results.json",
    }
)

PATH_LIKE = re.compile(
    r"(?:"
    r"(?:tests|src|internal|lib|pkg|cmd)/[\w./_-]+"
    r"|[\w./_-]+\.(?:ts|tsx|js|jsx|py|go|rs|md|json)"
    r")",
    re.IGNORECASE,
)


def owner_for_path(relative_path: str, *, src_roots: tuple[str, ...] = ("src",)) -> WriteZoneOwner:
    normalized = relative_path.replace("\\", "/").lstrip("./")
    name = normalized.split("/")[-1]
    if normalized.startswith("tests/adversarial/"):
        return "tester"
    if normalized.startswith("tests/"):
        return "planner"
    if name in TESTER_DOC_NAMES or name.startswith("ui_"):
        return "tester"
    for root in src_roots:
        if normalized == root or normalized.startswith(f"{root}/"):
            return "coder"
    for root in ("internal/", "lib/", "pkg/", "cmd/"):
        if normalized.startswith(root):
            return "coder"
    if normalized.endswith(".md") and name not in TESTER_DOC_NAMES:
        return "planner"
    return "coder"


def paths_from_text(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in PATH_LIKE.finditer(text):
        value = match.group(0).strip("`'\"")
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def owners_for_paths(paths: list[str]) -> set[WriteZoneOwner]:
    return {owner_for_path(path) for path in paths if path}


def owners_for_failure_notes(notes: str, extra_paths: Optional[list[str]] = None) -> set[WriteZoneOwner]:
    paths = paths_from_text(notes)
    if extra_paths:
        paths.extend(extra_paths)
    return owners_for_paths(paths)


def collect_artifact_owners(artifact: TesterArtifact) -> set[WriteZoneOwner]:
    owners: set[WriteZoneOwner] = set()
    for defect in artifact.defects:
        if defect.owner:
            owners.add(defect.owner)
        elif defect.path:
            owners.add(owner_for_path(defect.path))
    adversarial_paths = [file.path for file in artifact.adversarial_tests]
    owners.update(owners_for_paths(adversarial_paths))
    if artifact.failure_notes:
        owners.update(owners_for_failure_notes(artifact.failure_notes, adversarial_paths))
    return owners


def retry_target(artifact: TesterArtifact) -> RetryTarget:
    owners = collect_artifact_owners(artifact)
    if "planner" in owners:
        return "blocked"
    if owners and owners <= {"tester"}:
        return "tester"
    if "coder" in owners:
        return "coder"
    if owners == {"tester"}:
        return "tester"
    return "coder"


def enrich_defects(artifact: TesterArtifact) -> list[Defect]:
    if artifact.defects:
        enriched: list[Defect] = []
        for defect in artifact.defects:
            owner = defect.owner or (owner_for_path(defect.path) if defect.path else None)
            enriched.append(defect.model_copy(update={"owner": owner}))
        return enriched
    if not artifact.passed and artifact.failure_notes:
        paths = paths_from_text(artifact.failure_notes)
        paths.extend(file.path for file in artifact.adversarial_tests)
        owner: WriteZoneOwner | None = None
        owners = owners_for_paths(paths) if paths else set()
        if owners == {"tester"}:
            owner = "tester"
        elif "coder" in owners:
            owner = "coder"
        elif "planner" in owners:
            owner = "planner"
        return [
            Defect(
                severity="P0",
                path=paths[0] if paths else None,
                owner=owner,
                message=artifact.failure_notes,
            )
        ]
    return []


def summarize_failure_notes(artifact: TesterArtifact) -> str:
    defects = enrich_defects(artifact)
    if defects:
        return "; ".join(defect.message for defect in defects)
    return artifact.failure_notes or "tester reported failing verification"
