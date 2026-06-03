import asyncio
import json
import sys
import time
import pytest
from pathlib import Path
from threading import Thread
from uuid import uuid4
from fastapi.testclient import TestClient
from unittest.mock import patch

from specforge.core import contracts as contract_models
from specforge.agents.cli_runner import CLIResult
from specforge.core.contracts import (
    ArtifactFile,
    CodeTesterArtifact,
    CoderArtifact,
    ContextManifestEntry,
    PrdPlannerArtifact,
    TestPlannerArtifact,
    verification_from_code,
    parse_json_artifact,
)
from specforge.documents.docs_io import (
    IterationDocs,
    compare_test_integrity,
    planning_integrity_manifest as build_planning_integrity_manifest,
    test_integrity_manifest as build_test_integrity_manifest,
)
from specforge.main import app, broker, job_queue, pipeline, ws_iteration
from specforge.core.models import IterationStatus
from specforge.policy.context_cache import CONTEXT_INDEX
from specforge.policy.context_manifest import RUNTIME_NOTES, read_jsonl, read_runtime_notes


client = TestClient(app)


def post_project(tmp_path, name: str, **extra):
    root = tmp_path / name
    root.mkdir()
    payload = {"root_path": str(root), "create_if_missing": False, "name": name, **extra}
    return client.post("/api/projects", json=payload)


def drain_jobs():
    job_queue.join()


def advance_through_planning_gates(iteration_id: str) -> None:
    """Answer discovery so dry-run can reach coder/tester."""
    for _ in range(12):
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
        status = detail["status"]
        if status == "awaiting_requirements_input":
            client.post(
                f"/api/iterations/{iteration_id}/answer-requirements",
                json={"answer": "Ship a minimal vertical slice first"},
            )
            continue
        return


def wait_for_requirements_input(iteration_id: str) -> None:
    for _ in range(12):
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
        if detail["status"] == "awaiting_requirements_input":
            return
        if detail["status"] in {"blocked", "blocked_user", "awaiting_verify_approval", "delivered", "stopped"}:
            return


def create_manual_iteration(project_name: str, *, mode: str = "real-cli") -> str:
    iteration_id = pipeline.db.create_iteration(
        project_name=f"{project_name}-{uuid4().hex[:6]}",
        goal="manual pipeline test",
        mode=mode,
        test_command=None,
    )
    pipeline.project_root(iteration_id).mkdir(parents=True, exist_ok=True)
    return iteration_id


def write_planning_docs(iteration_id: str) -> IterationDocs:
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    docs.write_text("prd.md", "# PRD\n")
    docs.write_text("testing_plan.md", "# Testing Plan\n")
    docs.write_text("context/for_coder.jsonl", '{"file":"prd.md"}\n{"file":"testing_plan.md"}\n')
    docs.write_text("context/for_tester.jsonl", '{"file":"prd.md"}\n{"file":"testing_plan.md"}\n')
    return docs


class SequenceRunner:
    def __init__(self, results: list[CLIResult]) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []
        self.cwd_history: list[Path | None] = []

    def run(self, command, cwd=None, on_output=None, *, iteration_id=None):
        self.commands.append(command)
        self.cwd_history.append(cwd)
        result = self.results.pop(0)
        if on_output and result.stdout:
            on_output("stdout", result.stdout)
        if on_output and result.stderr:
            on_output("stderr", result.stderr)
        return CLIResult(command=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

    def cancel(self, iteration_id: str) -> bool:
        return False


class RuntimeSyncRunner:
    def __init__(self, *, cleaned: list[str] | None = None, cancelled_all: list[str] | None = None) -> None:
        self.cleaned = cleaned or []
        self.cancelled_all = cancelled_all or []
        self.cancelled: list[str] = []

    def cleanup_registry_processes(self) -> list[str]:
        return list(self.cleaned)

    def cancel_all(self) -> list[str]:
        return list(self.cancelled_all)

    def cancel(self, iteration_id: str) -> bool:
        self.cancelled.append(iteration_id)
        return iteration_id in self.cancelled_all


def run_code_and_ui_tester(state: dict) -> dict:
    code_state = pipeline._code_tester_node(state)
    if code_state.get("pending_code_tester_json"):
        merged = dict(state)
        merged.update(code_state)
        return pipeline._ui_tester_node(merged)
    return code_state


def make_tester_json(*, passed: bool = True, failure_notes: str | None = None) -> str:
    payload = {
        "verify_report": "# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        "passed": passed,
        "ux_notes": ["代码审查未发现阻断性交付问题。"],
        "delivery_recommendations": ["交付前可补跑完整自动化。"],
        "adversarial_tests": [],
    }
    if failure_notes:
        payload["failure_notes"] = failure_notes
    return json.dumps(payload)


def test_delete_epic_and_iterations(tmp_path):
    project = post_project(tmp_path, "delete-epic")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "To delete"})
    epic_id = epic.json()["id"]
    iteration = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "remove me", "mode": "dry-run"},
    )
    iteration_id = iteration.json()["id"]
    drain_jobs()

    delete_iteration = client.delete(f"/api/iterations/{iteration_id}")
    assert delete_iteration.status_code == 200
    assert client.get(f"/api/iterations/{iteration_id}").status_code == 404

    epic_after = client.get(f"/api/epics/{epic_id}")
    assert epic_after.status_code == 200
    assert epic_after.json()["iteration_count"] == 0

    delete_epic = client.delete(f"/api/epics/{epic_id}")
    assert delete_epic.status_code == 200
    assert client.get(f"/api/epics/{epic_id}").status_code == 404


def test_delete_epic_stops_running_iteration(tmp_path):
    project = post_project(tmp_path, "delete-running")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "Running epic"})
    epic_id = epic.json()["id"]
    iteration = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "running", "mode": "dry-run"},
    )
    iteration_id = iteration.json()["id"]

    delete_epic = client.delete(f"/api/epics/{epic_id}")
    assert delete_epic.status_code == 200
    drain_jobs()
    assert client.get(f"/api/iterations/{iteration_id}").status_code == 404


def test_epic_allows_only_one_pipeline(tmp_path):
    project = post_project(tmp_path, "one-pipeline")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "Single pipeline epic"})
    epic_id = epic.json()["id"]

    first = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "first run", "mode": "dry-run"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "second run", "mode": "dry-run"},
    )
    assert second.status_code == 409


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    payload = resp.json()
    assert "ui" in payload
    assert "ui_install_hint" in payload


def test_environment_checks_api_shape():
    payload = {
        "status": "warning",
        "checked_at": "2026-06-02T00:00:00+00:00",
        "checks": [
            {
                "id": "claude_cli",
                "label": "Claude Code CLI",
                "status": "ok",
                "message": "Available",
                "detail": "claude 1.0",
                "hint": None,
            }
        ],
    }
    with patch("specforge.main.environment_checks", return_value=payload):
        resp = client.get("/api/environment/checks")

    assert resp.status_code == 200
    assert resp.json() == payload


def test_browse_project_directory(tmp_path):
    root = tmp_path / "browse-root"
    child = root / "child-app"
    root.mkdir()
    child.mkdir()
    resp = client.get("/api/projects/browse", params={"path": str(root)})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["path"] == str(root.resolve())
    assert payload["parent"] == str(tmp_path.resolve())
    assert any(entry["path"] == str(child.resolve()) for entry in payload["entries"])


def test_create_project_open_existing_folder(tmp_path):
    root = tmp_path / "existing-app"
    root.mkdir()
    resp = client.post(
        "/api/projects",
        json={"root_path": str(root), "create_if_missing": False, "description": "bound repo"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["root_path"] == str(root.resolve())
    assert payload["name"] == "existing-app"


def test_create_project_create_if_missing(tmp_path):
    root = tmp_path / "new-app"
    resp = client.post(
        "/api/projects",
        json={"root_path": str(root), "create_if_missing": True, "name": "new-app"},
    )
    assert resp.status_code == 200
    assert root.is_dir()
    assert resp.json()["root_path"] == str(root.resolve())


def test_duplicate_root_path_returns_409(tmp_path):
    root = tmp_path / "dup-app"
    root.mkdir()
    first = client.post("/api/projects", json={"root_path": str(root), "create_if_missing": False})
    assert first.status_code == 200
    second = client.post("/api/projects", json={"root_path": str(root), "create_if_missing": False, "name": "other"})
    assert second.status_code == 409


def test_update_project_root_path(tmp_path):
    old_root = tmp_path / "old-app"
    new_root = tmp_path / "new-app"
    old_root.mkdir()
    project = client.post("/api/projects", json={"root_path": str(old_root), "create_if_missing": False})
    project_id = project.json()["id"]
    resp = client.patch(
        f"/api/projects/{project_id}",
        json={"root_path": str(new_root), "create_if_missing": True},
    )
    assert resp.status_code == 200
    assert resp.json()["root_path"] == str(new_root.resolve())
    assert new_root.is_dir()


def test_delete_project(tmp_path):
    project = post_project(tmp_path, "delete-me")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "Epic"})
    assert epic.status_code == 200
    iteration = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic.json()["id"], "goal": "test delete", "mode": "dry-run"},
    )
    assert iteration.status_code == 200
    drain_jobs()

    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get("/api/epics", params={"project_id": project_id}).status_code == 404
    assert client.get("/api/iterations", params={"project_id": project_id}).json() == []


def test_iteration_workspace_under_project_root(tmp_path):
    project = post_project(tmp_path, "workspace-project")
    project_id = project.json()["id"]
    root_path = project.json()["root_path"]
    resp = client.post("/api/iterations", json={"project_id": project_id, "goal": "write under project", "mode": "dry-run"})
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)
    workspace = pipeline.project_root(iteration_id)
    docs_root = pipeline.docs_root(iteration_id)
    assert str(workspace).startswith(str((Path(root_path) / ".specforge" / "iterations").resolve()))
    assert (docs_root / "prd.md").exists()
    assert (Path(root_path) / "docs" / "00_convention.md").exists()
    assert (docs_root / "context" / "for_coder.jsonl").exists()
    assert (docs_root / "context" / "for_tester.jsonl").exists()
    coder_context = read_jsonl(docs_root / "context" / "for_coder.jsonl")
    assert any(line.file == "prd.md" and line.sha256 and line.freshness == "fresh" for line in coder_context)
    assert any(line.file == "testing_plan.md" and line.summary and line.sha256 for line in coder_context)
    assert (Path(root_path) / CONTEXT_INDEX).exists()


def test_create_project_and_filter_iterations(tmp_path):
    project = post_project(tmp_path, "project-a", description="demo")
    assert project.status_code == 200
    project_id = project.json()["id"]

    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ship a dashboard", "mode": "dry-run"},
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project_id
    drain_jobs()

    filtered = client.get(f"/api/iterations?project_id={project_id}")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["project_id"] == project_id


def test_create_epic_and_attach_iteration(tmp_path):
    project = post_project(tmp_path, "epic-project", description="demo")
    assert project.status_code == 200
    project_id = project.json()["id"]

    epic = client.post(
        "/api/epics",
        json={
            "project_id": project_id,
            "title": "Large requirement",
            "description": "Build a workbench",
            "acceptance_criteria": "- Iteration queue exists\n- Action panel exists",
        },
    )
    assert epic.status_code == 200
    epic_id = epic.json()["id"]
    assert epic.json()["status"] == "draft"

    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "first slice", "mode": "dry-run"},
    )
    assert resp.status_code == 200
    assert resp.json()["epic_id"] == epic_id
    drain_jobs()

    detail = client.get(f"/api/epics/{epic_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "active"
    assert detail.json()["iteration_count"] == 1
    assert detail.json()["iterations"][0]["epic_id"] == epic_id


def test_epic_status_delivered_after_all_iterations_deliver(tmp_path):
    project = post_project(tmp_path, "epic-delivered")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "Deliver all"})
    epic_id = epic.json()["id"]

    resp = client.post("/api/iterations", json={"project_id": project_id, "epic_id": epic_id, "goal": "ship", "mode": "dry-run"})
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)
    client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "ok"})
    drain_jobs()

    detail = client.get(f"/api/epics/{epic_id}")
    assert detail.json()["status"] == "delivered"
    assert detail.json()["delivered_count"] == 1


def test_discovery_answer_then_planner(tmp_path):
    project = post_project(tmp_path, "discovery-flow")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ambiguous dashboard", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_requirements_input"
    assert detail["pending_discovery"]["question"]
    assert detail["graph_next"] == ["requirements_input"]

    answer = client.post(
        f"/api/iterations/{iteration_id}/answer-requirements",
        json={"answer": "Prioritize admin users first"},
    )
    assert answer.status_code == 200
    advance_through_planning_gates(iteration_id)
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(doc["name"] == "prd" for doc in detail["documents"])
    assert len(detail["discovery_history"]) == 1
    assert detail["status"] == "awaiting_verify_approval"


def test_create_iteration_runs_dry_flow():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo", "goal": "ship a dashboard", "mode": "dry-run"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    drain_jobs()
    detail = client.get(f"/api/iterations/{data['id']}")
    assert detail.json()["status"] == "awaiting_requirements_input"


def test_dry_run_emits_semantic_events():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "semantic", "goal": "show readable agent activity", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    semantic = [event for event in detail["events"] if event["type"] in {"node.started", "node.completed", "artifact.created"}]

    assert any(
        event["payload"]["node"] == "planner_discovery" and event["type"] == "node.started"
        for event in semantic
    )
    assert any(event["type"] == "discovery.question" for event in detail["events"])
    assert all({"node", "title", "message", "severity"}.issubset(event["payload"]) for event in semantic)


def test_iteration_detail_includes_documents():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo2", "goal": "make a thing", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert any(doc["name"] == "prd" for doc in payload["documents"])
    assert payload["runs"]


def test_iteration_detail_uses_lean_run_metadata_and_logs_endpoint():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "lean-runs", "goal": "make logs small", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    run = detail["runs"][0]

    assert "stdout" not in run or run["stdout"] is None
    assert "stderr" not in run or run["stderr"] is None
    assert run["stdout_bytes"] > 0
    assert run["duration_ms"] is not None
    assert run["logs_url"].endswith(f"/api/iterations/{iteration_id}/runs/{run['id']}/logs")

    logs = client.get(run["logs_url"]).json()
    assert logs["stdout"]
    assert "dry-run" in logs["stdout"]


def test_iteration_detail_compacts_large_history_for_live_refresh():
    iteration_id = create_manual_iteration("lean-history")
    pipeline.db.update_iteration(
        iteration_id,
        status=IterationStatus.blocked.value,
        current_node=None,
        stopped_at_node="ui_tester",
        last_error="error " + ("x" * 12000),
    )
    pipeline.db.add_run(
        iteration_id,
        node="ui_tester",
        status="failed",
        command="claude -p --json-schema {} ## SpecForge stage: ui_tester\n" + ("prompt " * 4000),
        stdout="full stdout",
        stderr="",
        exit_code=1,
    )
    pipeline.db.add_event(
        iteration_id,
        event_type="node.completed",
        payload={"node": "code_tester", "title": "Code Tester 完成", "message": "kept"},
    )
    for index in range(150):
        pipeline.db.add_event(
            iteration_id,
            event_type="cli.display",
            payload={
                "node": "ui_tester",
                "phase": "tool",
                "title": f"tool {index}",
                "message": "chunk " + ("x" * 12000),
                "raw_event": {"large": "x" * 12000},
            },
        )

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    cli_events = [event for event in detail["events"] if event["type"] == "cli.display"]
    run = detail["runs"][0]

    assert len(cli_events) == pipeline._PUBLIC_CLI_DISPLAY_EVENT_LIMIT
    assert any(event["type"] == "node.completed" for event in detail["events"])
    assert all("raw_event" not in event["payload"] for event in cli_events)
    assert all(len(event["payload"]["message"]) < 4300 for event in cli_events)
    assert detail["last_error"] is not None
    assert len(detail["last_error"]) < 4300
    assert "[prompt omitted]" in run["command"]
    assert "prompt prompt prompt prompt" not in run["command"]


def test_design_to_delivery_flow():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo3", "goal": "ship end to end", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    detail = client.get(f"/api/iterations/{iteration_id}")
    assert detail.json()["status"] == "awaiting_verify_approval"

    after_verify = client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "ok"})
    assert after_verify.status_code == 200
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert detail.json()["status"] == "delivered"


def test_tester_writes_delivery_advice():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "advice", "goal": "ship with delivery advice", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    detail = client.get(f"/api/iterations/{iteration_id}").json()

    assert any(doc["name"] == "delivery_advice" for doc in detail["documents"])
    assert any(event["type"] == "code_tester.delivery_advice" for event in detail["events"])


def test_invalid_approval_returns_409():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo4", "goal": "reject early verify", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    advance_through_planning_gates(iteration_id)
    client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "ok"})
    drain_jobs()

    invalid_verify = client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "already delivered"})
    assert invalid_verify.status_code == 409


def test_project_config_is_inherited(tmp_path):
    project = post_project(
        tmp_path,
        "configured",
        default_mode="dry-run",
        default_test_command="pytest",
        max_coder_tester_retries=2,
    )
    assert project.status_code == 200
    project_id = project.json()["id"]

    update = client.patch(f"/api/projects/{project_id}", json={"max_coder_tester_retries": 3})
    assert update.status_code == 200
    assert update.json()["max_coder_tester_retries"] == 3

    resp = client.post("/api/iterations", json={"project_id": project_id, "goal": "inherit defaults"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "dry-run"
    advance_through_planning_gates(resp.json()["id"])
    detail = client.get(f"/api/iterations/{resp.json()['id']}")
    assert detail.json()["test_command"] == "pytest"


def test_parse_claude_wrapped_artifact():
    raw = '{"type":"result","result":"{\\"prd\\":\\"a\\",\\"context_for_coder\\":[{\\"file\\":\\"prd.md\\",\\"reason\\":\\"r\\"}],\\"context_for_tester\\":[{\\"file\\":\\"prd.md\\",\\"reason\\":\\"r\\"}]}"}'
    artifact = parse_json_artifact(raw, PrdPlannerArtifact)
    assert artifact.prd == "a"


def test_parse_artifact_from_stream_json_lines():
    raw = (
        '{"type":"system","subtype":"init"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}\n'
        '{"type":"result","result":"{\\"testing_plan\\":\\"c\\",\\"tests\\":[]}"}\n'
    )
    artifact = parse_json_artifact(raw, TestPlannerArtifact)
    assert artifact.testing_plan == "c"


def test_parse_artifact_from_codex_jsonl_item_message():
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"verify_report\\":\\"# Verify Report\\\\nPass\\",\\"passed\\":true,\\"ux_notes\\":[],\\"delivery_recommendations\\":[],\\"adversarial_tests\\":[]}"}}\n'
    )
    artifact = parse_json_artifact(raw, contract_models.CodeTesterArtifact)
    assert artifact.passed is True
    assert "Pass" in artifact.verify_report


def test_code_tester_contract_rehomes_misplaced_adversarial_test_file():
    raw = json.dumps(
        {
            "verify_report": "# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
            "passed": True,
            "test_files": [
                {
                    "path": "tests/adversarial/stats-history.test.ts",
                    "content": "test('stats history edge case', () => {});\n",
                },
                {
                    "path": "tests/unit/stats.test.ts",
                    "content": "test('stats', () => {});\n",
                },
            ],
        }
    )

    artifact = parse_json_artifact(raw, CodeTesterArtifact)
    verification = verification_from_code(artifact)

    assert [file.path for file in artifact.test_files] == ["tests/unit/stats.test.ts"]
    assert [file.path for file in artifact.adversarial_tests] == ["tests/adversarial/stats-history.test.ts"]
    assert [file.path for file in verification.test_files] == ["tests/unit/stats.test.ts"]
    assert [file.path for file in verification.adversarial_tests] == ["tests/adversarial/stats-history.test.ts"]


def test_execute_jsonl_output_emits_cli_display_event():
    iteration_id = create_manual_iteration("cli-display")
    pipeline.db.update_iteration(iteration_id, current_node="code_tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "code_tester"}
    code = "import json; print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':['pytest','-q']}}))"

    pipeline._execute(
        state,
        [
            "python",
            "-c",
            code,
        ],
        node="code_tester",
    )
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    event = next(event for event in detail["events"] if event["type"] == "cli.display")
    assert event["payload"]["phase"] == "command"
    assert event["payload"]["command"] == "pytest -q"
    assert event["payload"]["provider"] == "codex"


def test_execute_non_json_output_falls_back_to_node_progress():
    iteration_id = create_manual_iteration("cli-fallback")
    pipeline.db.update_iteration(iteration_id, current_node="code_tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "code_tester"}

    pipeline._execute(state, ["python", "-c", "print('plain output')"], node="code_tester")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "node.progress" and event["payload"]["title"] == "已收到模型输出" for event in detail["events"])


def test_execute_stderr_jsonl_emits_cli_display_without_error_warning():
    iteration_id = create_manual_iteration("cli-stderr-jsonl")
    pipeline.db.update_iteration(iteration_id, current_node="code_tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "code_tester"}
    code = (
        "import json, sys; "
        "print(json.dumps({'type':'thread.started'})); "
        "print(json.dumps({'type':'turn.started'}), file=sys.stderr)"
    )

    pipeline._execute(state, ["python", "-c", code], node="code_tester")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "cli.display" for event in detail["events"])
    assert not any(
        event["type"] == "node.progress" and event["payload"].get("title") == "已收到错误输出"
        for event in detail["events"]
    )


def test_execute_throttles_text_cli_display_persistence():
    iteration_id = create_manual_iteration("cli-display-throttle")
    pipeline.db.update_iteration(iteration_id, current_node="planner_discovery", status="planning", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "planner_discovery"}
    text_line = json.dumps({"type": "stream_event", "stream_event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "thinking"}}})
    code = (
        "import json; "
        "print(json.dumps({'type':'system','subtype':'init'})); "
        f"[print({text_line!r}) for _ in range(50)]; "
        "print(json.dumps({'type':'result','result':'{}'}))"
    )

    pipeline._execute(state, [sys.executable, "-c", code], node="planner_discovery")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    cli_events = [event for event in detail["events"] if event["type"] == "cli.display"]

    assert len(cli_events) == 2
    phases = [event["payload"]["phase"] for event in cli_events]
    assert phases == ["session", "result"]
    assert all("raw_event" not in event["payload"] for event in cli_events)


def test_execute_stderr_plain_logs_use_diagnostic_title():
    iteration_id = create_manual_iteration("cli-stderr-plain")
    pipeline.db.update_iteration(iteration_id, current_node="code_tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "code_tester"}
    code = "import sys; print('stdout ok'); print('stderr diag', file=sys.stderr)"

    pipeline._execute(state, ["python", "-c", code], node="code_tester")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "node.progress" and event["payload"].get("title") == "CLI 诊断输出" for event in detail["events"])
    assert not any(
        event["type"] == "node.progress" and event["payload"].get("title") == "已收到错误输出"
        for event in detail["events"]
    )


def test_real_cli_execute_runs_from_project_root(tmp_path, monkeypatch):
    project = post_project(tmp_path, "real-cli-cwd")
    project_id = project.json()["id"]
    repo_root = Path(project.json()["root_path"])
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="cwd test",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    runner = SequenceRunner([CLIResult(command=[], returncode=0, stdout="ok", stderr="")])
    monkeypatch.setattr(pipeline, "real_runner", runner)

    pipeline._execute({"iteration_id": iteration_id, "mode": "real-cli", "project_id": project_id}, ["echo", "ok"], node="code_tester")

    assert runner.cwd_history == [repo_root]


def test_coder_prompt_points_to_project_src_and_iteration_docs(tmp_path):
    project = post_project(tmp_path, "coder-prompt")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="prompt test",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    state = {"iteration_id": iteration_id, "mode": "real-cli", "project_id": project_id}
    command = pipeline._coder_command(state)
    prompt = command[-1]

    assert "current working directory is the project root" in prompt
    assert "write zones" in prompt or "src/**" in prompt
    assert str(pipeline.docs_root(iteration_id)) in prompt


def test_tester_command_uses_project_cli_bindings(tmp_path):
    project = post_project(tmp_path, "cli-bindings")
    project_id = project.json()["id"]
    patch = client.patch(
        f"/api/projects/{project_id}",
        json={
            "cli_bindings": {
                "prd_planner": "claude",
                "planner_clarification": "claude",
                "coder": "claude",
                "code_tester": "claude",
            }
        },
    )
    assert patch.status_code == 200
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="cli binding test",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    state = {"iteration_id": iteration_id, "mode": "real-cli", "project_id": project_id}
    command = pipeline._code_tester_command(state)
    assert command[0] == "claude"


def test_planner_verify_reject_routes_back_to_code_tester():
    state = {"iteration_id": "iter", "route": "verify_rejected"}
    assert pipeline._route_after_planner_verify(state) == "code_tester"


def test_route_after_ui_tester_self_retry():
    state = {"iteration_id": "iter", "route": "self_retry"}
    assert pipeline._route_after_ui_tester(state) == "self_retry"


def test_route_after_ui_tester_coder_retry():
    state = {"iteration_id": "iter", "route": "retry"}
    assert pipeline._route_after_ui_tester(state) == "retry"


def test_route_tester_failure_routes_adversarial_to_self():
    from specforge.contracts import Defect, VerificationArtifact

    iteration_id = create_manual_iteration("code-tester-self-retry")
    artifact = VerificationArtifact(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[
            Defect(
                severity="P0",
                path="tests/adversarial/bad.test.ts",
                owner="code_tester",
                message="bad import",
            )
        ],
    )
    result = pipeline._route_tester_failure(
        {
            "iteration_id": iteration_id,
            "retry_counts": {},
            "max_tester_self_retries": 3,
            "max_coder_tester_retries": 5,
        },
        "run-1",
        artifact,
    )
    assert result["route"] == "self_retry"
    assert result["retry_target"] == "code_tester"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["retry_counts"]["code_tester_self"] == 1
    assert "code_tester.retry_to_self" in [event["type"] for event in detail["events"]]


def test_route_tester_failure_routes_src_to_coder():
    from specforge.contracts import Defect, VerificationArtifact

    iteration_id = create_manual_iteration("code-tester-coder-retry")
    artifact = VerificationArtifact(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[Defect(severity="P0", path="src/app.ts", owner="coder", message="bug")],
    )
    result = pipeline._route_tester_failure(
        {
            "iteration_id": iteration_id,
            "retry_counts": {},
            "max_tester_self_retries": 3,
            "max_coder_tester_retries": 5,
        },
        "run-2",
        artifact,
    )
    assert result["route"] == "retry"
    assert result["retry_target"] == "coder"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["retry_counts"]["coder_tester"] == 1
    assert "code_tester.retry_to_coder" in [event["type"] for event in detail["events"]]


def test_route_tester_failure_forces_p0_p1_to_fail_and_retry_coder():
    from specforge.contracts import Defect, VerificationArtifact

    iteration_id = create_manual_iteration("ui-p0-p1-passed-true")
    artifact = VerificationArtifact(
        verify_report="# Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        defects=[Defect(severity="P1", path="src/app.ts", owner="coder", message="checkout button is broken")],
    )
    normalized = pipeline._normalize_tester_artifact(artifact)

    assert normalized.passed is False
    result = pipeline._route_tester_failure(
        {
            "iteration_id": iteration_id,
            "retry_counts": {},
            "max_tester_self_retries": 3,
            "max_coder_tester_retries": 5,
        },
        "run-p1",
        artifact,
    )
    assert result["route"] == "retry"
    assert result["retry_target"] == "coder"


def test_normalize_tester_artifact_keeps_failed_ui_result_nonblocking_without_defect():
    from specforge.contracts import UITestResult, VerificationArtifact

    artifact = VerificationArtifact(
        verify_report="# Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        ui_results=[
            UITestResult(
                id="mt-01",
                title="Checkout flow",
                kind="web",
                status="failed",
                driver="playwright",
                error="Expected Pay button to be visible",
            )
        ],
    )

    normalized = pipeline._normalize_tester_artifact(artifact)

    assert normalized.passed is True
    assert normalized.defects == []
    assert normalized.failure_notes is None


def test_ensure_verify_report_markers_adds_title_and_pass_summary():
    normalized = pipeline._ensure_verify_report_markers("plain report without markers")
    assert "# " in normalized
    assert "Pass" in normalized
    assert "## Summary" in normalized


def test_ensure_verify_report_markers_preserves_existing_structure():
    original = "# Verify Report\n\n## Summary\n- Pass: 2\n- Fail: 1\n"
    assert pipeline._ensure_verify_report_markers(original) == original


def test_tester_retry_prompt_handles_verify_report_rejection(tmp_path):
    project = post_project(tmp_path, "tester-verify-retry")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="verify report retry",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    prompt = pipeline._code_tester_prompt(
        {
            "iteration_id": iteration_id,
            "mode": "real-cli",
            "project_id": project_id,
            "failure_notes": "verify_report missing required summary markers",
        },
        review_only=False,
    )

    assert "regenerate verify_report" in prompt
    assert "not a Coder src/** change" in prompt


def test_tester_review_fallback_succeeds_without_retry(monkeypatch):
    iteration_id = create_manual_iteration("tester-review-fallback", mode="real-cli")
    runner = SequenceRunner(
        [
            CLIResult(command=[], returncode=1, stdout="", stderr="Playwright browser is not installed"),
            CLIResult(command=[], returncode=0, stdout=make_tester_json(), stderr=""),
            CLIResult(command=[], returncode=0, stdout=make_tester_json(), stderr=""),
        ]
    )
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = run_code_and_ui_tester(
        {
            "iteration_id": iteration_id,
            "mode": "real-cli",
            "retry_counts": {},
            "max_coder_tester_retries": 5,
        }
    )

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert result["status"] == IterationStatus.awaiting_verify_approval.value
    assert detail["status"] == "awaiting_verify_approval"
    assert detail["retry_counts"] == {}
    assert len(runner.commands) == 3
    assert any("Do not invoke Playwright" in part for part in runner.commands[1])
    assert any("Manual Tests" in part for part in runner.commands[2])
    event_types = [event["type"] for event in detail["events"]]
    assert "code_tester.review_fallback.started" in event_types
    ui_payload = client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").json()
    assert "代码审查兜底" in ui_payload["warnings"][0]


def test_tester_accepts_valid_artifact_from_nonzero_exit(monkeypatch):
    iteration_id = create_manual_iteration("tester-nonzero-artifact", mode="real-cli")
    runner = SequenceRunner(
        [
            CLIResult(command=[], returncode=1, stdout=make_tester_json(), stderr="cua-driver exited 1"),
            CLIResult(command=[], returncode=0, stdout=make_tester_json(), stderr=""),
        ]
    )
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = run_code_and_ui_tester(
        {
            "iteration_id": iteration_id,
            "mode": "real-cli",
            "retry_counts": {},
            "max_coder_tester_retries": 5,
        }
    )

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert result["status"] == IterationStatus.awaiting_verify_approval.value
    assert detail["status"] == "awaiting_verify_approval"
    assert detail["retry_counts"] == {}
    assert len(runner.commands) == 2
    assert any(event["type"] == "code_tester.nonzero_artifact.accepted" for event in detail["events"])


def test_tester_review_fallback_failure_uses_existing_retry_path(monkeypatch):
    iteration_id = create_manual_iteration("tester-review-fallback-fails", mode="real-cli")
    runner = SequenceRunner(
        [
            CLIResult(command=[], returncode=1, stdout="", stderr="CuaDriver permission denied"),
            CLIResult(command=[], returncode=2, stdout="", stderr="review fallback failed"),
        ]
    )
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = run_code_and_ui_tester(
        {
            "iteration_id": iteration_id,
            "mode": "real-cli",
            "retry_counts": {},
            "max_coder_tester_retries": 0,
        }
    )

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert result["status"] == "blocked"
    assert detail["status"] == "blocked"
    assert detail["retry_counts"]["coder_tester"] == 1
    event_types = [event["type"] for event in detail["events"]]
    assert "code_tester.review_fallback.started" in event_types
    assert "code_tester.max_retries" in event_types


def test_execute_live_cli_node_from_db_current_node():
    iteration_id = create_manual_iteration("live-cli-node", mode="dry-run")
    pipeline.db.update_iteration(iteration_id, current_node="prd_planner", status="planning")
    state = {"iteration_id": iteration_id, "mode": "dry-run", "current_node": None}

    pipeline._reset_live_cli(iteration_id, "prd_planner")
    pipeline._execute(state, ["echo", "prd"], node="prd_planner")
    snapshot = pipeline._live_cli_snapshot(iteration_id)
    assert snapshot is not None
    assert snapshot["node"] == "prd_planner"

    pipeline.db.update_iteration(iteration_id, current_node="coder")
    pipeline._reset_live_cli(iteration_id, "coder")
    pipeline._execute(state, ["echo", "coder"])
    snapshot = pipeline._live_cli_snapshot(iteration_id)
    assert snapshot is not None
    assert snapshot["node"] == "coder"


def test_append_live_cli_publishes_cli_output_event():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "cli-output-event", "goal": "stream chunks", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    pipeline._reset_live_cli(iteration_id, "prd_planner")
    queue = pipeline.broker.subscribe(iteration_id)
    try:
        pipeline._append_live_cli(iteration_id, "stdout", "hello")
        pipeline._flush_cli_output(iteration_id)
        envelope = queue.get(timeout=1)
        assert envelope.type == "cli.output"
        assert envelope.event is not None
        assert envelope.event["payload"]["node"] == "prd_planner"
        assert envelope.event["payload"]["stream"] == "stdout"
        assert envelope.event["payload"]["chunk"] == "hello"
    finally:
        pipeline.broker.unsubscribe(iteration_id, queue)


def test_ws_iteration_send_after_close_is_ignored():
    class ClosedWebSocket:
        async def accept(self):
            return None

        async def close(self, code=1000):
            return None

        async def receive_json(self):
            await asyncio.sleep(60)

        async def send_json(self, payload):
            raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'")

    iteration_id = create_manual_iteration("ws-closed", mode="dry-run")

    asyncio.run(ws_iteration(ClosedWebSocket(), iteration_id))

    assert iteration_id not in broker._subscribers


def test_stop_iteration_cancels_active_cli():
    runner = pipeline.real_runner
    iteration_id = create_manual_iteration("stop-cli")
    results: list = []

    def run_process() -> None:
        results.append(
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                iteration_id=iteration_id,
            )
        )

    thread = Thread(target=run_process, daemon=True)
    thread.start()
    time.sleep(0.3)
    pipeline.stop_iteration(iteration_id, "stopped for test")
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert results
    assert results[0].returncode != 0


def test_delete_iteration_cancels_active_cli(tmp_path):
    project = post_project(tmp_path, "delete-cli")
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "CLI cancel epic"})
    epic_id = epic.json()["id"]
    iteration = client.post(
        "/api/iterations",
        json={"project_id": project_id, "epic_id": epic_id, "goal": "running cli", "mode": "dry-run"},
    )
    iteration_id = iteration.json()["id"]
    runner = pipeline.real_runner
    results: list = []

    def run_process() -> None:
        results.append(
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                iteration_id=iteration_id,
            )
        )

    thread = Thread(target=run_process, daemon=True)
    thread.start()
    time.sleep(0.3)
    delete = client.delete(f"/api/iterations/{iteration_id}")
    assert delete.status_code == 200
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert results
    assert results[0].returncode != 0
    assert client.get(f"/api/iterations/{iteration_id}").status_code == 404


def test_stop_iteration_records_stopped_at_node():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "stop-node", "goal": "record stop step", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    pipeline.db.update_iteration(iteration_id, current_node="planner_discovery", status="planning")
    pipeline.stop_iteration(iteration_id, "stopped for test")
    row = pipeline.db.get_iteration_row(iteration_id)
    assert row["status"] == "stopped"
    assert row["stopped_at_node"] == "planner_discovery"


def test_resync_runtime_state_stops_active_iterations():
    iteration_id = create_manual_iteration("runtime-resync", mode="real-cli")
    pipeline.db.update_iteration(iteration_id, status="coding", current_node="coder", last_error=None)
    original_runner = pipeline.real_runner
    pipeline.real_runner = RuntimeSyncRunner(cleaned=[iteration_id])  # type: ignore[assignment]
    try:
        assert pipeline.resync_runtime_state() == [iteration_id]
    finally:
        pipeline.real_runner = original_runner

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "stopped"
    assert detail["stopped_at_node"] == "coder"
    assert "service restarted" in detail["last_error"]
    assert any(event["type"] == "runtime.resynced" for event in detail["events"])


def test_resync_runtime_state_preserves_waiting_iterations():
    waiting_id = create_manual_iteration("runtime-waiting", mode="dry-run")
    approval_id = create_manual_iteration("runtime-approval", mode="dry-run")
    pipeline.db.update_iteration(waiting_id, status="awaiting_requirements_input", current_node=None, last_error=None)
    pipeline.db.update_iteration(approval_id, status="awaiting_verify_approval", current_node=None, last_error=None)
    original_runner = pipeline.real_runner
    pipeline.real_runner = RuntimeSyncRunner()  # type: ignore[assignment]
    try:
        pipeline.resync_runtime_state()
    finally:
        pipeline.real_runner = original_runner

    assert client.get(f"/api/iterations/{waiting_id}").json()["status"] == "awaiting_requirements_input"
    assert client.get(f"/api/iterations/{approval_id}").json()["status"] == "awaiting_verify_approval"


def test_shutdown_cancels_cli_and_stops_active_iteration():
    iteration_id = create_manual_iteration("runtime-shutdown", mode="real-cli")
    pipeline.db.update_iteration(iteration_id, status="testing", current_node="code_tester", last_error=None)
    original_runner = pipeline.real_runner
    runner = RuntimeSyncRunner(cancelled_all=[iteration_id])
    pipeline.real_runner = runner  # type: ignore[assignment]
    try:
        assert pipeline.shutdown() == [iteration_id]
    finally:
        pipeline.real_runner = original_runner

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "stopped"
    assert detail["stopped_at_node"] == "code_tester"
    assert detail["last_error"] == "service shutting down"


def test_planner_clarification_writes_question_and_answer(tmp_path):
    project = post_project(tmp_path, "clarify-flow")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="clarify path",
        mode="dry-run",
        test_command=None,
        project_id=project_id,
    )
    pipeline._prepare_iteration_docs(iteration_id)
    state = {
        "iteration_id": iteration_id,
        "mode": "dry-run",
        "clarification_request": "Should src live under api/ or services/?",
        "retry_counts": {},
        "max_clarifications": 3,
    }
    result = pipeline._planner_clarification_node(state)
    assert result["status"] == "coding"
    docs_root = pipeline.docs_root(iteration_id)
    assert (docs_root / "clarifications" / "01_question.md").exists()
    assert (docs_root / "clarifications" / "01_answer.md").exists()
    assert "clarification.answered" in [event["type"] for event in pipeline.db.list_events(iteration_id)]


class ClarificationFailRunner:
    """Dry-run runner that fails on the Nth planner_clarification invocation."""

    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on
        self.clarify_calls = 0
        self._dry = pipeline.dry_runner

    def run(self, command, cwd=None, on_output=None, *, iteration_id=None):
        if command and command[0] == "specforge" and len(command) > 1 and command[1] == "planner_clarification":
            self.clarify_calls += 1
            if self.clarify_calls >= self.fail_on:
                result = CLIResult(
                    command=command,
                    returncode=1,
                    stdout="",
                    stderr="simulated planner clarification failure",
                )
                if on_output and result.stderr:
                    on_output("stderr", result.stderr)
                return result
        return self._dry.run(command, cwd=cwd, on_output=on_output, iteration_id=iteration_id)

    def cancel(self, iteration_id: str) -> bool:
        return False


def test_double_clarification_loop_reaches_verify_approval(tmp_path, monkeypatch):
    project = post_project(tmp_path, "double-clarify-ok")
    project_id = project.json()["id"]
    coder_calls = {"count": 0}
    original_coder_artifact = pipeline._coder_artifact

    def clarifying_coder_artifact(state, run_result):
        coder_calls["count"] += 1
        if coder_calls["count"] <= 2:
            return CoderArtifact(
                changed_paths=[],
                summary=f"needs clarification #{coder_calls['count']}",
                clarification_request=f"Question {coder_calls['count']}?",
            )
        return original_coder_artifact(state, run_result)

    monkeypatch.setattr(pipeline, "_coder_artifact", clarifying_coder_artifact)

    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "two clarification rounds", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == IterationStatus.awaiting_verify_approval.value
    assert detail["retry_counts"]["coder_planner_clarify"] == 2
    assert coder_calls["count"] == 3
    answered = [event for event in detail["events"] if event["type"] == "clarification.answered"]
    assert len(answered) == 2
    assert not any(event["type"] == "job.failed" for event in detail["events"])


def test_double_clarification_cli_failure_blocks_without_langgraph_error(tmp_path, monkeypatch):
    project = post_project(tmp_path, "double-clarify-fail")
    project_id = project.json()["id"]
    coder_calls = {"count": 0}
    original_coder_artifact = pipeline._coder_artifact

    def clarifying_coder_artifact(state, run_result):
        coder_calls["count"] += 1
        if coder_calls["count"] <= 2:
            return CoderArtifact(
                changed_paths=[],
                summary=f"needs clarification #{coder_calls['count']}",
                clarification_request=f"Question {coder_calls['count']}?",
            )
        return original_coder_artifact(state, run_result)

    monkeypatch.setattr(pipeline, "_coder_artifact", clarifying_coder_artifact)
    monkeypatch.setattr(pipeline, "dry_runner", ClarificationFailRunner(fail_on=2))

    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "second clarify fails", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == IterationStatus.blocked.value
    assert detail["retry_counts"]["coder_planner_clarify"] == 2
    assert any(event["type"] == "planner_clarification.failed" for event in detail["events"])
    assert not any(event["type"] == "job.failed" for event in detail["events"])
    assert "simulated planner clarification failure" in detail["last_error"]
    assert "INVALID_CONCURRENT_GRAPH_UPDATE" not in (detail["last_error"] or "")


def test_format_cli_failure_uses_exit_code_when_stderr_empty():
    result = CLIResult(command=["missing-cli"], returncode=127, stdout="", stderr="")
    message = pipeline._format_cli_failure(result)
    assert "127" in message or "未找到" in message


def test_resume_stopped_iteration(tmp_path):
    project = post_project(tmp_path, "resume-stopped")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "resume after stop", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    pipeline.db.update_iteration(
        iteration_id,
        status="stopped",
        current_node=None,
        stopped_at_node="planner_discovery",
        last_error="user stopped",
    )
    resume = client.post(f"/api/iterations/{iteration_id}/resume", json={"note": "continue"})
    assert resume.status_code == 200
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] != "stopped"
    assert any(event["type"] == "iteration.resumed" for event in detail["events"])
    notes = read_runtime_notes(pipeline.docs_root(iteration_id) / RUNTIME_NOTES)
    assert notes[-1] == {"node": "planner_discovery", "note": "continue"}
    resumed = [event for event in detail["events"] if event["type"] == "iteration.resumed"]
    assert resumed[-1]["payload"]["note"] == "continue"


def test_runtime_note_accepts_stopped_iteration(tmp_path):
    project = post_project(tmp_path, "stopped-runtime-note")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "add stopped note", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    pipeline.db.update_iteration(
        iteration_id,
        status="stopped",
        current_node=None,
        stopped_at_node="coder",
        last_error="user stopped",
    )

    resp = client.post(
        f"/api/iterations/{iteration_id}/runtime-note",
        json={"note": "prefer the compact admin table"},
    )

    assert resp.status_code == 200
    notes = read_runtime_notes(pipeline.docs_root(iteration_id) / RUNTIME_NOTES)
    assert notes[-1] == {"node": "coder", "note": "prefer the compact admin table"}
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    runtime_note_events = [event for event in detail["events"] if event["type"] == "runtime.note"]
    assert runtime_note_events[-1]["payload"]["node"] == "coder"


def test_manual_skip_code_tester_reaches_verify_approval():
    iteration_id = create_manual_iteration("manual-skip-code-tester", mode="dry-run")
    pipeline.db.update_iteration(
        iteration_id,
        status="blocked",
        current_node=None,
        last_error="tester artifact invalid",
    )

    resp = client.post(
        f"/api/iterations/{iteration_id}/manual-skip",
        json={"node": "code_tester", "note": "debug skip"},
    )
    assert resp.status_code == 200

    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_verify_approval"
    assert detail["last_error"] is None
    event_types = [event["type"] for event in detail["events"]]
    assert "manual_skip.queued" in event_types
    assert "manual_skip.started" in event_types
    assert "ui_tester.completed" in event_types


def test_manual_skip_rejects_delivered_iteration():
    iteration_id = create_manual_iteration("manual-skip-delivered", mode="dry-run")
    pipeline.db.update_iteration(iteration_id, status="delivered", current_node=None, last_error=None)

    resp = client.post(
        f"/api/iterations/{iteration_id}/manual-skip",
        json={"node": "verify_approval", "note": "too late"},
    )

    assert resp.status_code == 409


def test_tester_write_rejects_tests_ui_artifact(tmp_path):
    project = post_project(tmp_path, "ui-spec-tester")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ui spec validation", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        test_files=[ArtifactFile(path="tests/ui/bad.json", content="{}")],
    )
    with pytest.raises(ValueError, match="tests/ui artifacts are no longer generated"):
        pipeline._write_tester_artifact(iteration_id, docs, artifact)


def test_tester_write_rehomes_misplaced_adversarial_test_file():
    iteration_id = create_manual_iteration("misplaced-adversarial", mode="dry-run")
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        test_files=[
            ArtifactFile(
                path="tests/adversarial/stats-history.test.ts",
                content="test('stats history edge case', () => {});\n",
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)

    path = docs.root / "tests" / "adversarial" / "stats-history.test.ts"
    assert path.exists()
    assert "tests/adversarial/stats-history.test.ts" not in build_test_integrity_manifest(docs.root)


def test_tester_write_allows_new_project_test_file(tmp_path):
    project = post_project(tmp_path, "project-test-file", default_mode="dry-run")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="allow project test",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        test_files=[
            ArtifactFile(
                path="backend/internal/service/setting_service_public_test.go",
                content="package service\n\nfunc TestPublicSettings(t *testing.T) {}\n",
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)

    project_root = Path(project.json()["root_path"])
    path = project_root / "backend/internal/service/setting_service_public_test.go"
    assert path.exists()
    assert "TestPublicSettings" in path.read_text(encoding="utf-8")


def test_tester_write_allows_overwriting_existing_project_test_file(tmp_path):
    project = post_project(tmp_path, "project-test-overwrite", default_mode="dry-run")
    project_id = project.json()["id"]
    project_root = Path(project.json()["root_path"])
    existing = project_root / "backend/internal/service/setting_service_public_test.go"
    existing.parent.mkdir(parents=True)
    existing.write_text("package service\n", encoding="utf-8")
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="allow overwrite",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        test_files=[
            ArtifactFile(
                path="backend/internal/service/setting_service_public_test.go",
                content="package service\n\nfunc TestPublicSettings(t *testing.T) {}\n",
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)
    assert existing.read_text(encoding="utf-8") == "package service\n\nfunc TestPublicSettings(t *testing.T) {}\n"


def test_tester_write_allows_idempotent_existing_project_test_file(tmp_path):
    project = post_project(tmp_path, "project-test-idempotent", default_mode="dry-run")
    project_id = project.json()["id"]
    project_root = Path(project.json()["root_path"])
    existing = project_root / "backend/internal/service/setting_service_public_test.go"
    content = "package service\n\nfunc TestPublicSettings(t *testing.T) {}\n"
    existing.parent.mkdir(parents=True)
    existing.write_text(content, encoding="utf-8")
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="allow idempotent test replay",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        test_files=[
            ArtifactFile(
                path="backend/internal/service/setting_service_public_test.go",
                content=content,
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)

    assert existing.read_text(encoding="utf-8") == content


def test_tester_write_allows_project_adversarial_test_file(tmp_path):
    project = post_project(tmp_path, "project-adversarial-test-file", default_mode="dry-run")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="allow project adversarial test",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        adversarial_tests=[
            ArtifactFile(
                path="backend/internal/service/changelog_adversarial_test.go",
                content="package service\n\nfunc TestChangelogAdversarial(t *testing.T) {}\n",
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)

    project_root = Path(project.json()["root_path"])
    path = project_root / "backend/internal/service/changelog_adversarial_test.go"
    assert path.exists()
    assert "TestChangelogAdversarial" in path.read_text(encoding="utf-8")


def test_tester_write_allows_overwriting_project_adversarial_file(tmp_path):
    project = post_project(tmp_path, "project-adversarial-overwrite", default_mode="dry-run")
    project_id = project.json()["id"]
    project_root = Path(project.json()["root_path"])
    existing = project_root / "backend/internal/service/changelog_adversarial_test.go"
    existing.parent.mkdir(parents=True)
    existing.write_text("package service\n", encoding="utf-8")
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="allow adversarial overwrite",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        adversarial_tests=[
            ArtifactFile(
                path="backend/internal/service/changelog_adversarial_test.go",
                content="package service\n\nfunc TestChangelogAdversarial(t *testing.T) {}\n",
            )
        ],
    )

    pipeline._write_tester_artifact(iteration_id, docs, artifact)
    assert existing.read_text(encoding="utf-8") == "package service\n\nfunc TestChangelogAdversarial(t *testing.T) {}\n"


def test_tester_write_rejects_non_test_project_file(tmp_path):
    project = post_project(tmp_path, "project-non-test-file", default_mode="dry-run")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="reject non test",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = CodeTesterArtifact(
        verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
        passed=True,
        test_files=[
            ArtifactFile(
                path="backend/internal/service/setting_service.go",
                content="package service\n",
            )
        ],
    )

    with pytest.raises(ValueError, match="not a recognized test file"):
        pipeline._write_tester_artifact(iteration_id, docs, artifact)


def test_tests_ui_tree_is_not_protected_by_checksum(tmp_path):
    root = tmp_path / "docs"
    legacy_spec = root / "tests" / "ui" / "web_smoke.json"
    recording = root / "tests" / "ui" / "recordings" / "web_smoke" / "frame.json"
    legacy_spec.parent.mkdir(parents=True)
    recording.parent.mkdir(parents=True)
    legacy_spec.write_text('{"id":"web_smoke"}', encoding="utf-8")
    baseline = build_test_integrity_manifest(root)
    recording.write_text('{"ok":true}', encoding="utf-8")
    assert compare_test_integrity(root, baseline) == []


def test_checksum_gate_blocks_modified_protected_tests():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "integrity", "goal": "protect tests", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    # Simulate Code Tester writing a test and establishing baseline
    test_file = pipeline.docs_root(iteration_id) / "tests" / "unit" / "test_transitions.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    pipeline._update_iteration(
        iteration_id,
        test_integrity_baseline=build_test_integrity_manifest(docs.root),
    )

    # Now modify the test (simulating Coder tampering on retry)
    test_file.write_text("def test_bad():\n    assert True\n", encoding="utf-8")

    result = pipeline._integrity_check_node({"iteration_id": iteration_id})
    assert result["status"] == "blocked"
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert "modified protected test" in detail.json()["last_error"]
    payload = detail.json()
    classified = [event for event in payload["events"] if event["type"] == "error.classified"]
    assert classified
    assert "测试基线" in classified[-1]["payload"]["action_hint"]


def test_planning_integrity_blocks_modified_plan_after_coder():
    iteration_id = create_manual_iteration("planning-integrity", mode="dry-run")
    docs = write_planning_docs(iteration_id)
    pipeline._update_iteration(
        iteration_id,
        status="coding",
        current_node=None,
        planning_integrity_baseline=build_planning_integrity_manifest(docs.root),
    )

    (docs.root / "testing_plan.md").write_text("# Tampered Plan\n", encoding="utf-8")

    result = pipeline._coder_node({"iteration_id": iteration_id, "mode": "dry-run", "retry_counts": {}})

    assert result["status"] == "blocked"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert "modified planning document: testing_plan.md" in detail["last_error"]
    assert any(event["type"] == "planning_integrity.failed" for event in detail["events"])
    classified = [event for event in detail["events"] if event["type"] == "error.classified"]
    assert classified[-1]["payload"]["title"] == "规划文档完整性失败"


def test_artifact_invalid_retries_same_agent_before_blocking():
    from specforge.core.contracts import PlannerDiscoveryArtifact

    original_prd = pipeline._prd_planner_artifact
    original_discovery = pipeline._planner_discovery_artifact

    def ready_discovery(state, run_result):
        return PlannerDiscoveryArtifact(status="ready", requirements_brief="Ready to plan.", complexity="simple")

    attempts = {"count": 0}

    def first_bad_then_valid_prd(state, run_result):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("prd planner returned invalid JSON")
        return PrdPlannerArtifact(
            prd="# PRD\n",
            context_for_coder=[ContextManifestEntry(file="prd.md", reason="r")],
            context_for_tester=[ContextManifestEntry(file="prd.md", reason="r")],
        )

    pipeline._planner_discovery_artifact = ready_discovery  # type: ignore[method-assign]
    pipeline._prd_planner_artifact = first_bad_then_valid_prd  # type: ignore[method-assign]
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "invalid-artifact", "goal": "bad planner output", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._prd_planner_artifact = original_prd  # type: ignore[method-assign]
        pipeline._planner_discovery_artifact = original_discovery  # type: ignore[method-assign]

    assert attempts["count"] == 2
    assert detail["status"] == "awaiting_verify_approval"
    assert detail["retry_counts"]["prd_planner_artifact_self"] == 1
    assert detail["last_error"] is None
    assert any(event["type"] == "artifact.invalid" for event in detail["events"])
    retry_events = [event for event in detail["events"] if event["type"] == "artifact.retry_to_self"]
    assert retry_events[-1]["payload"]["retry_target"] == "prd_planner"
    assert retry_events[-1]["payload"]["stderr"] == "prd planner returned invalid JSON"


def test_artifact_invalid_blocks_after_self_retry_limit():
    iteration_id = create_manual_iteration("artifact-self-limit", mode="dry-run")

    result = pipeline._route_artifact_self_retry(
        {
            "iteration_id": iteration_id,
            "retry_counts": {"code_tester_artifact_self": 3},
            "max_tester_self_retries": 3,
        },
        "code_tester",
        "run-1",
        "invalid artifact again",
    )

    assert result["status"] == "blocked"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["retry_counts"]["code_tester_artifact_self"] == 4
    assert any(event["type"] == "artifact.self_max_retries" for event in detail["events"])
    classified = [event for event in detail["events"] if event["type"] == "error.classified"]
    assert classified[-1]["payload"]["title"] == "Agent 产物自修已达上限"


def test_code_tester_write_error_routes_to_self_retry(tmp_path):
    project = post_project(tmp_path, "tester-artifact-self", default_mode="dry-run")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="tester artifact write issue",
        mode="dry-run",
        test_command=None,
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    artifact = verification_from_code(
        CodeTesterArtifact(
            verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
            passed=True,
            test_files=[
                ArtifactFile(
                    path="backend/internal/service/setting_service.go",
                    content="package service\n",
                )
            ],
        )
    )

    with pytest.raises(ValueError) as exc:
        pipeline._write_tester_artifact(iteration_id, docs, artifact, run_id="run-2")
    result = pipeline._route_artifact_self_retry(
        {
            "iteration_id": iteration_id,
            "retry_counts": {},
            "max_tester_self_retries": 3,
        },
        "code_tester",
        "run-2",
        str(exc.value),
    )

    assert result["route"] == "artifact_self_retry"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "retrying"
    assert detail["retry_counts"]["code_tester_artifact_self"] == 1
    assert any(event["type"] == "artifact.retry_to_self" for event in detail["events"])


def test_code_tester_artifact_retry_notes_are_in_prompt(tmp_path):
    project = post_project(tmp_path, "tester-artifact-prompt", default_mode="real-cli")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        project_id=project_id,
        goal="retry artifact prompt",
        mode="real-cli",
        test_command=None,
    )
    state = {
        "iteration_id": iteration_id,
        "project_id": project_id,
        "mode": "real-cli",
        "route": "artifact_self_retry",
        "retry_target": "code_tester",
        "failure_notes": "tester test_files path is not a recognized test file: backend/foo.go",
    }

    prompt = pipeline._code_tester_prompt(state, review_only=False)

    assert "Artifact self-retry" in prompt
    assert "tester test_files path is not a recognized test file" in prompt


def test_tester_failure_retries_until_blocked(tmp_path):
    project = post_project(tmp_path, "retry-project", default_mode="dry-run", max_coder_tester_retries=1)
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "force tester failure"},
    )
    iteration_id = resp.json()["id"]
    advance_through_planning_gates(iteration_id)

    detail = client.get(f"/api/iterations/{iteration_id}")
    payload = detail.json()
    assert payload["status"] == "blocked"
    assert payload["retry_counts"]["coder_tester"] == 2
    assert "forced tester failure" in payload["last_error"]


def test_ui_tester_playwright_passes_web(monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_name": "ui-playwright", "goal": "run UI playwright", "mode": "dry-run"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_tester.completed" for event in detail["events"])
    assert detail["ui_results"][0]["status"] == "passed"
    assert detail["ui_results"][0]["driver"] == "playwright"


def test_ui_tester_cua_unavailable_native_warns_web_pass(monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_name": "ui-mixed", "goal": "run UI mixed", "mode": "dry-run"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_tester.warning" for event in detail["events"])
    assert detail["ui_results"][0]["id"] == "manual_plan"
    assert detail["ui_results"][0]["status"] == "warning"


def test_ui_tester_playwright_unavailable_web_warns(monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_name": "ui-dual-fail", "goal": "run UI dual fail", "mode": "dry-run"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_tester.warning" for event in detail["events"])
    assert detail["ui_results"][0]["status"] == "warning"


def test_ui_tester_pass_writes_results_and_artifacts(monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_name": "ui-pass", "goal": "run UI pass", "mode": "dry-run"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "awaiting_verify_approval"
    assert detail["ui_results"][0]["status"] == "passed"
    assert any(doc["name"] == "ui_report" for doc in detail["documents"])
    assert any(doc["name"] == "ui_results" for doc in detail["documents"])
    assert client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").status_code == 200


def test_ui_tester_automation_failure_warns_without_p0_p1(tmp_path, monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        project = post_project(tmp_path, "ui-fail-project", default_mode="dry-run", max_coder_tester_retries=1)
        project_id = project.json()["id"]
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_id": project_id, "goal": "run UI fail", "mode": "dry-run"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "awaiting_verify_approval"
    assert detail["retry_counts"] == {}
    ui_progress = [
        event
        for event in detail["events"]
        if event["type"] == "node.progress" and event["payload"].get("node") == "ui_tester"
    ]
    assert ui_progress[-1]["payload"]["severity"] == "warning"
    assert "UI 场景未通过" in ui_progress[-1]["payload"]["message"]
    failed_event = next(event for event in detail["events"] if event["type"] == "ui_tester.failed")
    assert failed_event["payload"]["blocking"] is False
    assert "code_tester.retry_to_coder" not in [event["type"] for event in detail["events"]]
    assert detail["ui_results"][0]["status"] == "failed"
    ui_payload = client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").json()
    assert "未汇总为 P0/P1 缺陷" in ui_payload["warnings"][0]


def test_ui_tester_p0_p1_summary_retries_to_coder(monkeypatch):
    from specforge.contracts import Defect, UITestResult, VerificationArtifact

    iteration_id = create_manual_iteration("ui-summary-p1", mode="dry-run")
    docs = write_planning_docs(iteration_id)
    baseline = verification_from_code(
        CodeTesterArtifact(
            verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
            passed=True,
        )
    )

    def ui_artifact(state, baseline, docs, *, run_id):
        return (
            VerificationArtifact(
                verify_report="# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
                passed=True,
                defects=[Defect(severity="P1", path="src/app.ts", owner="coder", message="primary action is hidden")],
                ui_results=[
                    UITestResult(
                        id="mt-01",
                        title="Primary action",
                        kind="web",
                        status="passed",
                        driver="playwright",
                    )
                ],
            ),
            run_id,
        )

    monkeypatch.setattr(pipeline, "_run_ui_tester_agent", ui_artifact)

    result = pipeline._ui_tester_node(
        {
            "iteration_id": iteration_id,
            "mode": "dry-run",
            "retry_counts": {},
            "max_tester_self_retries": 3,
            "max_coder_tester_retries": 5,
            "pending_code_tester_json": baseline.model_dump_json(),
        }
    )

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert result["route"] == "retry"
    assert result["retry_target"] == "coder"
    assert detail["retry_counts"]["coder_tester"] == 1
    assert "code_tester.retry_to_coder" in [event["type"] for event in detail["events"]]


def test_artifact_gate_failure_skips_ui_tester(tmp_path, monkeypatch):
    original_planner = pipeline._test_planner_artifact
    pipeline._test_planner_artifact = make_test_planner_ui_plan  # type: ignore[method-assign]
    try:
        project = post_project(
            tmp_path,
            "gate-before-ui",
            default_mode="dry-run",
            default_test_command=f"{sys.executable} -c \"import sys; sys.exit(7)\"",
            max_coder_tester_retries=0,
        )
        project_id = project.json()["id"]
        iteration_id, detail = create_iteration_with_manual_ui_plan(
            {"project_id": project_id, "goal": "run UI plan but fail gate"},
            monkeypatch,
        )
    finally:
        pipeline._test_planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "blocked"
    assert any(event["type"] == "code_tester.max_retries" for event in detail["events"])
    assert not any(event["payload"].get("node") == "ui_tester" for event in detail["events"] if isinstance(event.get("payload"), dict))
    assert detail["ui_results"] == []


def create_iteration_with_manual_ui_plan(payload: dict, monkeypatch=None) -> tuple[str, dict]:
    if monkeypatch is not None:
        monkeypatch.setattr(pipeline, "_is_real_cli", lambda mode: False)
    resp = client.post("/api/iterations", json=payload)
    iteration_id = resp.json()["id"]
    wait_for_requirements_input(iteration_id)
    client.post(
        f"/api/iterations/{iteration_id}/answer-requirements",
        json={"answer": "Ship the UI acceptance path"},
    )
    drain_jobs()
    return iteration_id, client.get(f"/api/iterations/{iteration_id}").json()


def make_test_planner_ui_plan(state, run_result):
    return TestPlannerArtifact(
        testing_plan="# Tests\n\n## Manual Tests\n\n### MT-01: UI smoke\n\nOpen the app and verify the primary UI state.",
    )


def test_planning_session_id_in_state_after_discovery(tmp_path, monkeypatch):
    project = post_project(tmp_path, "planning-session")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="session test",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    runner = SequenceRunner([CLIResult(command=[], returncode=0, stdout="ok", stderr="")])
    monkeypatch.setattr(pipeline, "real_runner", runner)

    state = {"iteration_id": iteration_id, "mode": "real-cli", "project_id": project_id, "goal": "session test"}
    cmd = pipeline._planner_discovery_command(state)
    assert any(part.startswith("--session-id") or part == "--session-id" for part in cmd)
    session_id = state.get("planning_cli_session_id")
    assert session_id is not None

    pipeline._mark_planning_session_started(state)
    assert state["planning_cli_session_started"] is True

    cmd2 = pipeline._prd_planner_command(state)
    assert "--resume" in cmd2
    assert session_id in cmd2


def test_planning_nodes_persist_and_resume_session(tmp_path, monkeypatch):
    from specforge.core.contracts import PlannerDiscoveryArtifact

    project = post_project(tmp_path, "planning-session-prod")
    project_id = project.json()["id"]
    iteration_id = pipeline.db.create_iteration(
        project_name=project.json()["name"],
        goal="session production test",
        mode="real-cli",
        test_command=None,
        project_id=project_id,
    )
    runner = SequenceRunner([
        CLIResult(command=[], returncode=0, stdout="discovery", stderr=""),
        CLIResult(command=[], returncode=0, stdout="prd", stderr=""),
        CLIResult(command=[], returncode=0, stdout="tests", stderr=""),
    ])
    monkeypatch.setattr(pipeline, "real_runner", runner)
    monkeypatch.setattr(
        pipeline,
        "_planner_discovery_artifact",
        lambda state, run_result: PlannerDiscoveryArtifact(status="ready", requirements_brief="Ready.", complexity="simple"),
    )
    monkeypatch.setattr(
        pipeline,
        "_prd_planner_artifact",
        lambda state, run_result: PrdPlannerArtifact(
            prd="# PRD\n",
            context_for_coder=[ContextManifestEntry(file="prd.md", reason="r")],
            context_for_tester=[ContextManifestEntry(file="prd.md", reason="r")],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_test_planner_artifact",
        lambda state, run_result: TestPlannerArtifact(testing_plan="# Testing Plan\n"),
    )

    state = pipeline._build_state(iteration_id)
    discovery_state = pipeline._planner_discovery_node(state)
    state.update(discovery_state)
    prd_state = pipeline._prd_planner_node(state)
    state.update(prd_state)
    pipeline._test_planner_node(state)

    row = pipeline.db.get_iteration_row(iteration_id)
    assert row is not None
    assert row["planning_cli_session_id"]
    assert row["planning_cli_session_started"] == 1
    session_id = row["planning_cli_session_id"]
    assert "--session-id" in runner.commands[0]
    assert "--resume" in runner.commands[1]
    assert session_id in runner.commands[1]
    assert "--resume" in runner.commands[2]
    assert session_id in runner.commands[2]


def test_discovery_routes_back_to_itself_after_answer(tmp_path):
    project = post_project(tmp_path, "discovery-loop")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ambiguous dashboard", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_requirements_input"
    assert detail["graph_next"] == ["requirements_input"]

    answer = client.post(
        f"/api/iterations/{iteration_id}/answer-requirements",
        json={"answer": "Prioritize admin users first"},
    )
    assert answer.status_code == 200
    drain_jobs()

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_verify_approval"
    assert len(detail["discovery_history"]) == 1


def test_pending_discovery_falls_back_to_question_event():
    iteration_id = create_manual_iteration("discovery-event-fallback", mode="dry-run")
    pipeline.db.update_iteration(iteration_id, status="awaiting_requirements_input", current_node=None)
    pipeline.db.add_event(
        iteration_id,
        event_type="discovery.question",
        payload={
            "round": 1,
            "question": "Which user segment should be prioritized?",
            "options": ["Admins", "Operators", "其他（请说明）"],
            "assumptions": ["dashboard workflow"],
        },
    )

    detail = client.get(f"/api/iterations/{iteration_id}").json()

    assert detail["pending_discovery"] == {
        "round": 1,
        "question": "Which user segment should be prioritized?",
        "options": ["Admins", "Operators", "其他（请说明）"],
        "assumptions": ["dashboard workflow"],
    }


def test_multi_round_discovery_with_resume(monkeypatch):
    from specforge.core.contracts import PlannerDiscoveryArtifact

    call_count = {"n": 0}
    original = pipeline._planner_discovery_artifact

    def multi_discovery(state, run_result):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return PlannerDiscoveryArtifact(
                status="ask",
                complexity="moderate",
                question="Which tech stack?",
                options=["React", "Vue", "其他（请说明）"],
                assumptions=["web app"],
                requirements_brief="Goal: build a dashboard",
                rationale="Need stack info",
            )
        if call_count["n"] == 2:
            return PlannerDiscoveryArtifact(
                status="ask",
                complexity="moderate",
                question="Auth provider?",
                options=["OAuth", "SAML", "其他（请说明）"],
                assumptions=["web app", "React"],
                requirements_brief="Goal: build a React dashboard",
                rationale="Need auth info",
            )
        return PlannerDiscoveryArtifact(
            status="ready",
            complexity="moderate",
            assumptions=["web app", "React", "OAuth"],
            requirements_brief="Goal: build a React dashboard with OAuth",
            rationale="All clear",
        )

    monkeypatch.setattr(pipeline, "_planner_discovery_artifact", multi_discovery)

    resp = client.post(
        "/api/iterations",
        json={"project_name": "multi-discovery", "goal": "build dashboard", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_requirements_input"
    assert detail["pending_discovery"]["question"] == "Which tech stack?"

    client.post(
        f"/api/iterations/{iteration_id}/answer-requirements",
        json={"answer": "React"},
    )
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_requirements_input"
    assert detail["pending_discovery"]["question"] == "Auth provider?"
    assert len(detail["discovery_history"]) == 1

    client.post(
        f"/api/iterations/{iteration_id}/answer-requirements",
        json={"answer": "OAuth"},
    )
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] == "awaiting_verify_approval"
    assert len(detail["discovery_history"]) == 2

    monkeypatch.setattr(pipeline, "_planner_discovery_artifact", original)


def test_reset_live_cli_continuing_preserves_output():
    iteration_id = create_manual_iteration("live-cli-continue", mode="dry-run")
    pipeline._reset_live_cli(iteration_id, "planner_discovery")
    pipeline._append_live_cli(iteration_id, "stdout", "discovery output\n")

    pipeline._reset_live_cli(iteration_id, "prd_planner", continuing=True)
    snapshot = pipeline._live_cli_snapshot(iteration_id)
    assert snapshot is not None
    assert "discovery output" in snapshot["stdout"]
    assert "--- prd_planner ---" in snapshot["stdout"]
    assert snapshot["node"] == "prd_planner"


def test_reset_live_cli_non_continuing_clears_output():
    iteration_id = create_manual_iteration("live-cli-clear", mode="dry-run")
    pipeline._reset_live_cli(iteration_id, "planner_discovery")
    pipeline._append_live_cli(iteration_id, "stdout", "discovery output\n")

    pipeline._reset_live_cli(iteration_id, "coder")
    snapshot = pipeline._live_cli_snapshot(iteration_id)
    assert snapshot is not None
    assert snapshot["stdout"] == ""
    assert snapshot["node"] == "coder"
