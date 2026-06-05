from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agents.cli_commands import DEFAULT_CLI_BINDINGS, CliStage, parse_cli_bindings, resolve_cli_provider
from .policy.context_manifest import read_jsonl, read_runtime_notes


PROFILE_STAGES: tuple[CliStage, ...] = (
    "planner_discovery",
    "prd_planner",
    "test_planner",
    "planner_clarification",
    "coder",
    "code_tester",
    "ui_tester",
)

STAGE_LABELS: dict[str, str] = {
    "planner_discovery": "需求澄清",
    "prd_planner": "PRD 规划",
    "test_planner": "测试规划",
    "planner_clarification": "规划澄清",
    "coder": "实现",
    "code_tester": "代码验证",
    "integrity_check": "测试完整性",
    "ui_tester": "UI 验证",
    "planner_verify": "规格复核",
    "verify_approval": "交付确认",
    "done": "交付完成",
}

DEFAULT_SESSION_POLICY: dict[str, str] = {
    "planner_discovery": "continue planning session after first turn",
    "prd_planner": "continue planning session",
    "test_planner": "continue planning session",
    "planner_clarification": "new session",
    "coder": "new session; retry continue best-effort",
    "code_tester": "new session; self-retry continue best-effort",
    "integrity_check": "system check",
    "ui_tester": "new session; self-retry continue best-effort",
    "planner_verify": "system review",
    "verify_approval": "human approval",
    "done": "archive",
}

PIPELINE_NODES: tuple[str, ...] = (
    "planner_discovery",
    "prd_planner",
    "test_planner",
    "coder",
    "code_tester",
    "integrity_check",
    "ui_tester",
    "planner_verify",
    "verify_approval",
    "done",
)

PIPELINE_EDGES: tuple[dict[str, str], ...] = (
    {"from": "planner_discovery", "to": "prd_planner", "on": "ready"},
    {"from": "planner_discovery", "to": "planner_discovery", "on": "artifact_self_retry"},
    {"from": "prd_planner", "to": "test_planner", "on": "success"},
    {"from": "test_planner", "to": "coder", "on": "success"},
    {"from": "coder", "to": "planner_clarification", "on": "clarification"},
    {"from": "planner_clarification", "to": "coder", "on": "answered"},
    {"from": "coder", "to": "code_tester", "on": "success"},
    {"from": "code_tester", "to": "coder", "on": "retry"},
    {"from": "code_tester", "to": "code_tester", "on": "self_retry"},
    {"from": "code_tester", "to": "test_planner", "on": "test_planner_retry"},
    {"from": "code_tester", "to": "integrity_check", "on": "passed"},
    {"from": "integrity_check", "to": "ui_tester", "on": "passed"},
    {"from": "ui_tester", "to": "coder", "on": "retry"},
    {"from": "ui_tester", "to": "code_tester", "on": "self_retry"},
    {"from": "ui_tester", "to": "planner_verify", "on": "passed"},
    {"from": "planner_verify", "to": "code_tester", "on": "rejected"},
    {"from": "planner_verify", "to": "verify_approval", "on": "accepted"},
    {"from": "verify_approval", "to": "done", "on": "approved"},
)


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    name: str
    summary: str
    stage: str
    content: str
    created_at: str
    updated_at: str
    path: str

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "stage": self.stage,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "path": self.path,
        }


def context_root(project_root: Path) -> Path:
    return project_root / ".specforge" / "context"


def profiles_dir(project_root: Path) -> Path:
    return context_root(project_root) / "profiles"


def bindings_path(project_root: Path) -> Path:
    return context_root(project_root) / "profile-bindings.json"


def list_project_profiles(project_root: Path) -> list[ProjectProfile]:
    root = profiles_dir(project_root)
    if not root.is_dir():
        return []
    profiles = [_read_profile(path, project_root) for path in sorted(root.glob("*.md"))]
    return sorted((profile for profile in profiles if profile is not None), key=lambda item: (item.stage, item.name, item.id))


def get_project_profile(project_root: Path, profile_id: str) -> ProjectProfile | None:
    for profile in list_project_profiles(project_root):
        if profile.id == profile_id:
            return profile
    return None


def create_project_profile(project_root: Path, *, name: str, summary: str, stage: str, content: str) -> ProjectProfile:
    _validate_stage(stage)
    now = _now()
    profile = ProjectProfile(
        id=f"pf_{uuid4().hex[:8]}",
        name=name.strip(),
        summary=summary.strip(),
        stage=stage,
        content=content.strip(),
        created_at=now,
        updated_at=now,
        path="",
    )
    return _write_profile(project_root, profile)


def update_project_profile(project_root: Path, profile_id: str, *, name: str, summary: str, stage: str, content: str) -> ProjectProfile:
    _validate_stage(stage)
    existing = get_project_profile(project_root, profile_id)
    if existing is None:
        raise KeyError(profile_id)
    updated = ProjectProfile(
        id=existing.id,
        name=name.strip(),
        summary=summary.strip(),
        stage=stage,
        content=content.strip(),
        created_at=existing.created_at,
        updated_at=_now(),
        path=existing.path,
    )
    old_path = project_root / existing.path
    profile = _write_profile(project_root, updated)
    new_path = project_root / profile.path
    if old_path != new_path and old_path.exists():
        old_path.unlink()
    _normalize_bindings_after_profile_stage_change(project_root, profile)
    return profile


def delete_project_profile(project_root: Path, profile_id: str) -> bool:
    profile = get_project_profile(project_root, profile_id)
    if profile is None:
        return False
    path = project_root / profile.path
    if path.exists():
        path.unlink()
    bindings = load_profile_bindings(project_root)
    changed = False
    for stage, bound_id in list(bindings.items()):
        if bound_id == profile_id:
            bindings[stage] = None
            changed = True
    if changed:
        save_profile_bindings(project_root, bindings)
    return True


def load_profile_bindings(project_root: Path) -> dict[str, str | None]:
    path = bindings_path(project_root)
    if not path.exists():
        return {stage: None for stage in PROFILE_STAGES}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    bindings: dict[str, str | None] = {stage: None for stage in PROFILE_STAGES}
    if isinstance(raw, dict):
        for stage in PROFILE_STAGES:
            value = raw.get(stage)
            bindings[stage] = str(value) if isinstance(value, str) and value.strip() else None
    profile_ids = {profile.id for profile in list_project_profiles(project_root)}
    return {stage: profile_id if profile_id in profile_ids else None for stage, profile_id in bindings.items()}


def save_profile_bindings(project_root: Path, bindings: dict[str, str | None]) -> dict[str, str | None]:
    profile_by_id = {profile.id: profile for profile in list_project_profiles(project_root)}
    cleaned: dict[str, str | None] = {stage: None for stage in PROFILE_STAGES}
    for stage in PROFILE_STAGES:
        value = bindings.get(stage)
        if value is None or value == "":
            cleaned[stage] = None
            continue
        profile = profile_by_id.get(str(value))
        if profile is None:
            raise ValueError(f"profile not found: {value}")
        if profile.stage != stage:
            raise ValueError(f"profile {value} belongs to {profile.stage}, not {stage}")
        cleaned[stage] = profile.id
    path = bindings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return cleaned


def bound_profile_for_stage(project_root: Path, stage: str) -> ProjectProfile | None:
    if stage not in PROFILE_STAGES:
        return None
    profile_id = load_profile_bindings(project_root).get(stage)
    return get_project_profile(project_root, profile_id) if profile_id else None


def stage_profile_prompt(project_root: Path | None, stage: str) -> str:
    if project_root is None:
        return ""
    profile = bound_profile_for_stage(project_root, stage)
    if profile is None:
        return ""
    return (
        "## Project Profile\n"
        f"- id: {profile.id}\n"
        f"- name: {profile.name}\n"
        f"- summary: {profile.summary or '(none)'}\n"
        f"- stage: {profile.stage}\n\n"
        f"{profile.content}\n"
    )


def workflow_snapshot(*, project: Any | None, iteration: Any | None = None) -> dict[str, Any]:
    project_root = Path(project["root_path"]) if project is not None and project["root_path"] else None
    bindings_raw = parse_cli_bindings(project["cli_bindings"] if project is not None and "cli_bindings" in project.keys() else None)
    profile_bindings = load_profile_bindings(project_root) if project_root else {stage: None for stage in PROFILE_STAGES}
    profiles = {profile.id: profile for profile in list_project_profiles(project_root)} if project_root else {}
    retry_budget = {
        "coder_tester": int(project["max_coder_tester_retries"]) if project is not None else 5,
        "code_tester_self": int(project["max_tester_self_retries"]) if project is not None and "max_tester_self_retries" in project.keys() else 3,
        "clarifications": int(project["max_clarifications"]) if project is not None else 3,
        "verify_rejects": int(project["max_verify_rejects"]) if project is not None else 2,
        "discovery_rounds": int(project["max_discovery_rounds"]) if project is not None and "max_discovery_rounds" in project.keys() else 8,
    }
    nodes = []
    for node in PIPELINE_NODES:
        provider = resolve_cli_provider(bindings_raw, node) if node in DEFAULT_CLI_BINDINGS else None
        profile_id = profile_bindings.get(node)
        profile = profiles.get(profile_id) if profile_id else None
        nodes.append(
            {
                "id": node,
                "label": STAGE_LABELS.get(node, node),
                "provider": provider,
                "session_policy": DEFAULT_SESSION_POLICY.get(node, "new session"),
                "retry_budget": _retry_budget_for_node(node, retry_budget),
                "profile": profile.payload() if profile else None,
            }
        )
    return {
        "version": "0.1",
        "kind": "specforge-fixed-pipeline",
        "iteration_id": iteration["id"] if iteration is not None else None,
        "project_id": project["id"] if project is not None else None,
        "nodes": nodes,
        "edges": list(PIPELINE_EDGES),
        "retry_budget": retry_budget,
        "profile_bindings": profile_bindings,
    }


def context_package_for_run(*, project_root: Path, iteration_root: Path, docs_root: Path, run: Any, documents: list[Any], events: list[Any]) -> dict[str, Any]:
    node = run["node"]
    profile = bound_profile_for_stage(project_root, node)
    hot_doc_names = _hot_doc_names_for_node(node)
    hot_docs = []
    for document in documents:
        if document["name"] not in hot_doc_names:
            continue
        path = Path(document["path"])
        hot_docs.append(
            {
                "name": document["name"],
                "path": str(path),
                "exists": path.exists(),
                "preview": _read_preview(path),
            }
        )
    manifest_path = _manifest_path_for_node(docs_root, node)
    cold_manifest = [line.to_dict() for line in read_jsonl(manifest_path)] if manifest_path else []
    runtime_notes = read_runtime_notes(docs_root / "context" / "runtime_notes.jsonl")
    previous_feedback = _previous_feedback_for_node(events, node)
    return {
        "version": "0.1",
        "run_id": run["id"],
        "node": node,
        "profile": profile.payload() if profile else None,
        "hot_docs": hot_docs,
        "cold_manifest": cold_manifest,
        "runtime_notes": runtime_notes,
        "previous_feedback": previous_feedback,
        "iteration_root": str(iteration_root),
        "docs_root": str(docs_root),
    }


def context_metadata_for_stage(project_root: Path, docs_root: Path, stage: str, *, previous_feedback: str = "") -> dict[str, Any]:
    profile = bound_profile_for_stage(project_root, stage)
    manifest_path = _manifest_path_for_node(docs_root, stage)
    return {
        "profile": profile.payload() if profile else None,
        "hot_docs": _hot_doc_names_for_node(stage),
        "cold_manifest": [line.to_dict() for line in read_jsonl(manifest_path)] if manifest_path else [],
        "runtime_notes": read_runtime_notes(docs_root / "context" / "runtime_notes.jsonl"),
        "previous_feedback": previous_feedback,
    }


def _read_profile(path: Path, project_root: Path) -> ProjectProfile | None:
    text = path.read_text(encoding="utf-8")
    frontmatter, content = _split_frontmatter(text)
    profile_id = frontmatter.get("id") or path.stem
    name = frontmatter.get("name") or path.stem
    stage = frontmatter.get("stage") or ""
    if stage not in PROFILE_STAGES:
        return None
    return ProjectProfile(
        id=str(profile_id),
        name=str(name),
        summary=str(frontmatter.get("summary") or ""),
        stage=str(stage),
        content=content.strip(),
        created_at=str(frontmatter.get("created_at") or ""),
        updated_at=str(frontmatter.get("updated_at") or ""),
        path=path.relative_to(project_root).as_posix(),
    )


def _write_profile(project_root: Path, profile: ProjectProfile) -> ProjectProfile:
    root = profiles_dir(project_root)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(profile.name)}-{profile.id}.md"
    path = root / filename
    payload = (
        "---\n"
        f"id: {profile.id}\n"
        f"name: {profile.name}\n"
        f"summary: {profile.summary}\n"
        f"stage: {profile.stage}\n"
        f"created_at: {profile.created_at}\n"
        f"updated_at: {profile.updated_at}\n"
        "---\n\n"
        f"{profile.content.strip()}\n"
    )
    path.write_text(payload, encoding="utf-8")
    return ProjectProfile(**{**profile.payload(), "path": path.relative_to(project_root).as_posix()})


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    try:
        _, raw_frontmatter, content = text.split("---", 2)
    except ValueError:
        return {}, text
    data: dict[str, str] = {}
    for raw in raw_frontmatter.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        data[key.strip()] = value.strip()
    return data, content.lstrip("\n")


def _normalize_bindings_after_profile_stage_change(project_root: Path, profile: ProjectProfile) -> None:
    bindings = load_profile_bindings(project_root)
    changed = False
    for stage, profile_id in list(bindings.items()):
        if profile_id == profile.id and stage != profile.stage:
            bindings[stage] = None
            changed = True
    if changed:
        save_profile_bindings(project_root, bindings)


def _validate_stage(stage: str) -> None:
    if stage not in PROFILE_STAGES:
        raise ValueError(f"unsupported profile stage: {stage}")


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return text or "profile"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_budget_for_node(node: str, retry_budget: dict[str, int]) -> dict[str, int] | None:
    if node == "planner_discovery":
        return {"discovery_rounds": retry_budget["discovery_rounds"]}
    if node == "coder":
        return {"coder_tester": retry_budget["coder_tester"], "clarifications": retry_budget["clarifications"]}
    if node == "code_tester":
        return {"code_tester_self": retry_budget["code_tester_self"]}
    if node == "planner_verify":
        return {"verify_rejects": retry_budget["verify_rejects"]}
    return None


def _hot_doc_names_for_node(node: str) -> list[str]:
    if node in {"planner_discovery", "prd_planner"}:
        return ["requirements_brief"]
    if node == "test_planner":
        return ["requirements_brief", "prd"]
    if node in {"coder", "planner_clarification"}:
        return ["prd", "testing_plan"]
    if node in {"code_tester", "ui_tester", "planner_verify"}:
        return ["prd", "testing_plan", "verify_report", "ui_report"]
    return ["prd", "testing_plan", "verify_report", "delivery_advice"]


def _manifest_path_for_node(docs_root: Path, node: str) -> Path | None:
    if node in {"coder", "planner_clarification"}:
        return docs_root / "context" / "for_coder.jsonl"
    if node in {"code_tester", "ui_tester", "planner_verify"}:
        return docs_root / "context" / "for_tester.jsonl"
    return None


def _read_preview(path: Path, limit: int = 1200) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit] + ("..." if len(text) > limit else "")


def _previous_feedback_for_node(events: list[Any], node: str) -> list[dict[str, Any]]:
    interesting = []
    for event in events:
        try:
            payload = json.loads(event["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        event_node = payload.get("node")
        if event_node != node and event["type"] not in {"test_planner.retry", "provider.continue_fallback", "planner_verify.rejected"}:
            continue
        if event["type"].endswith("retry") or "retry" in event["type"] or event["type"] in {"provider.continue_fallback", "planner_verify.rejected"}:
            interesting.append(
                {
                    "type": event["type"],
                    "created_at": event["created_at"],
                    "message": payload.get("message") or payload.get("notes") or payload.get("reason") or "",
                }
            )
    return interesting[-6:]
