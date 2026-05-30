import json
import sys
import time
import pytest
from pathlib import Path
from threading import Thread
from uuid import uuid4
from fastapi.testclient import TestClient

from specforge import contracts as contract_models
from specforge.cli_runner import CLIResult
from specforge.contracts import ArtifactFile, CoderArtifact, PlannerArtifact, UIDriverRunResult, UITestResult, UITestSpec, parse_json_artifact, validate_ui_spec_content
from specforge.docs_io import IterationDocs, compare_test_integrity, test_integrity_manifest as build_test_integrity_manifest
from specforge.main import app, job_queue, pipeline
from specforge.models import IterationStatus


client = TestClient(app)


def post_project(tmp_path, name: str, **extra):
    root = tmp_path / name
    root.mkdir()
    payload = {"root_path": str(root), "create_if_missing": False, "name": name, **extra}
    return client.post("/api/projects", json=payload)


def drain_jobs():
    job_queue.join()


def create_manual_iteration(project_name: str, *, mode: str = "real-cli") -> str:
    iteration_id = pipeline.db.create_iteration(
        project_name=f"{project_name}-{uuid4().hex[:6]}",
        goal="manual pipeline test",
        mode=mode,
        test_command=None,
    )
    pipeline.project_root(iteration_id).mkdir(parents=True, exist_ok=True)
    return iteration_id


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
    drain_jobs()
    workspace = pipeline.project_root(iteration_id)
    docs_root = pipeline.docs_root(iteration_id)
    assert str(workspace).startswith(str((Path(root_path) / ".specforge" / "iterations").resolve()))
    assert (docs_root / "system_design.md").exists()
    assert (Path(root_path) / "docs" / "00_convention.md").exists()
    assert (Path(root_path) / "docs" / "04_decisions" / "ADR-001-langgraph.md").exists()


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
    drain_jobs()
    client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "ok"})
    drain_jobs()

    detail = client.get(f"/api/epics/{epic_id}")
    assert detail.json()["status"] == "delivered"
    assert detail.json()["delivered_count"] == 1


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
    assert detail.json()["status"] == "awaiting_verify_approval"


def test_dry_run_emits_semantic_events():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "semantic", "goal": "show readable agent activity", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    detail = client.get(f"/api/iterations/{iteration_id}").json()
    semantic = [event for event in detail["events"] if event["type"] in {"node.started", "node.completed", "artifact.created"}]

    assert any(event["payload"]["node"] == "planner" and event["type"] == "node.started" for event in semantic)
    assert any(event["type"] == "artifact.created" and event["payload"]["document"] == "system_design" for event in semantic)
    assert all({"node", "title", "message", "severity"}.issubset(event["payload"]) for event in semantic)


def test_iteration_detail_includes_documents():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo2", "goal": "make a thing", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert any(doc["name"] == "system_design" for doc in payload["documents"])
    assert payload["runs"]


def test_design_to_delivery_flow():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo3", "goal": "ship end to end", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

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
    drain_jobs()

    detail = client.get(f"/api/iterations/{iteration_id}").json()

    assert any(doc["name"] == "delivery_advice" for doc in detail["documents"])
    assert any(event["type"] == "tester.delivery_advice" for event in detail["events"])


def test_invalid_approval_returns_409():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo4", "goal": "reject early verify", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    invalid_design = client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "removed checkpoint"})
    assert invalid_design.status_code == 409

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
    drain_jobs()
    detail = client.get(f"/api/iterations/{resp.json()['id']}")
    assert detail.json()["test_command"] == "pytest"


def test_parse_claude_wrapped_artifact():
    raw = '{"type":"result","result":"{\\"system_design\\":\\"a\\",\\"modification_plan\\":\\"b\\",\\"testing_plan\\":\\"c\\",\\"tests\\":[{\\"path\\":\\"tests/unit/test_a.py\\",\\"content\\":\\"x\\"}]}"}'
    artifact = parse_json_artifact(raw, PlannerArtifact)
    assert artifact.system_design == "a"
    assert artifact.tests[0].path == "tests/unit/test_a.py"


def test_parse_artifact_from_stream_json_lines():
    raw = (
        '{"type":"system","subtype":"init"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}\n'
        '{"type":"result","result":"{\\"system_design\\":\\"a\\",\\"modification_plan\\":\\"b\\",\\"testing_plan\\":\\"c\\",\\"tests\\":[]}"}\n'
    )
    artifact = parse_json_artifact(raw, PlannerArtifact)
    assert artifact.system_design == "a"


def test_parse_artifact_from_codex_jsonl_item_message():
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"verify_report\\":\\"# Verify Report\\\\nPass\\",\\"passed\\":true,\\"ux_notes\\":[],\\"delivery_recommendations\\":[],\\"adversarial_tests\\":[]}"}}\n'
    )
    artifact = parse_json_artifact(raw, contract_models.TesterArtifact)
    assert artifact.passed is True
    assert "Pass" in artifact.verify_report


def test_execute_jsonl_output_emits_cli_display_event():
    iteration_id = create_manual_iteration("cli-display")
    pipeline.db.update_iteration(iteration_id, current_node="tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "tester"}
    code = "import json; print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':['pytest','-q']}}))"

    pipeline._execute(
        state,
        [
            "python",
            "-c",
            code,
        ],
        node="tester",
    )
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    event = next(event for event in detail["events"] if event["type"] == "cli.display")
    assert event["payload"]["phase"] == "command"
    assert event["payload"]["command"] == "pytest -q"
    assert event["payload"]["provider"] == "codex"


def test_execute_non_json_output_falls_back_to_node_progress():
    iteration_id = create_manual_iteration("cli-fallback")
    pipeline.db.update_iteration(iteration_id, current_node="tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "tester"}

    pipeline._execute(state, ["python", "-c", "print('plain output')"], node="tester")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "node.progress" and event["payload"]["title"] == "已收到模型输出" for event in detail["events"])


def test_execute_stderr_jsonl_emits_cli_display_without_error_warning():
    iteration_id = create_manual_iteration("cli-stderr-jsonl")
    pipeline.db.update_iteration(iteration_id, current_node="tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "tester"}
    code = (
        "import json, sys; "
        "print(json.dumps({'type':'thread.started'})); "
        "print(json.dumps({'type':'turn.started'}), file=sys.stderr)"
    )

    pipeline._execute(state, ["python", "-c", code], node="tester")
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "cli.display" for event in detail["events"])
    assert not any(
        event["type"] == "node.progress" and event["payload"].get("title") == "已收到错误输出"
        for event in detail["events"]
    )


def test_execute_stderr_plain_logs_use_diagnostic_title():
    iteration_id = create_manual_iteration("cli-stderr-plain")
    pipeline.db.update_iteration(iteration_id, current_node="tester", status="testing", last_error=None)
    state = {"iteration_id": iteration_id, "mode": "real-cli", "current_node": "tester"}
    code = "import sys; print('stdout ok'); print('stderr diag', file=sys.stderr)"

    pipeline._execute(state, ["python", "-c", code], node="tester")
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

    pipeline._execute({"iteration_id": iteration_id, "mode": "real-cli", "project_id": project_id}, ["echo", "ok"], node="tester")

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
    assert "Edit only project source files under src/**" in prompt
    assert str(pipeline.docs_root(iteration_id)) in prompt
    assert "Do not edit docs/**" in prompt


def test_tester_command_uses_project_cli_bindings(tmp_path):
    project = post_project(tmp_path, "cli-bindings")
    project_id = project.json()["id"]
    patch = client.patch(
        f"/api/projects/{project_id}",
        json={
            "cli_bindings": {
                "planner": "claude",
                "planner_clarification": "claude",
                "coder": "claude",
                "tester": "claude",
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
    command = pipeline._tester_command(state)
    assert command[0] == "claude"


def test_planner_verify_reject_routes_back_to_tester():
    state = {"iteration_id": "iter", "route": "verify_rejected"}
    assert pipeline._route_after_planner_verify(state) == "tester"


def test_route_after_tester_self_retry():
    state = {"iteration_id": "iter", "route": "self_retry"}
    assert pipeline._route_after_tester(state) == "self_retry"


def test_route_after_tester_coder_retry():
    state = {"iteration_id": "iter", "route": "retry"}
    assert pipeline._route_after_tester(state) == "retry"


def test_route_tester_failure_routes_adversarial_to_self():
    from specforge.contracts import Defect, TesterArtifact

    iteration_id = create_manual_iteration("tester-self-retry")
    artifact = TesterArtifact(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[
            Defect(
                severity="P0",
                path="tests/adversarial/bad.test.ts",
                owner="tester",
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
    assert result["retry_target"] == "tester"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["retry_counts"]["tester_self"] == 1
    assert "tester.retry_to_self" in [event["type"] for event in detail["events"]]


def test_route_tester_failure_routes_src_to_coder():
    from specforge.contracts import Defect, TesterArtifact

    iteration_id = create_manual_iteration("tester-coder-retry")
    artifact = TesterArtifact(
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
    assert "tester.retry_to_coder" in [event["type"] for event in detail["events"]]


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
    prompt = pipeline._tester_prompt(
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
        ]
    )
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = pipeline._tester_node(
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
    assert any("Do not invoke Playwright" in part for part in runner.commands[1])
    event_types = [event["type"] for event in detail["events"]]
    assert "tester.review_fallback.started" in event_types
    assert "tester.review_fallback.completed" in event_types
    ui_payload = client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").json()
    assert "代码审查兜底" in ui_payload["warnings"][0]


def test_tester_accepts_valid_artifact_from_nonzero_exit(monkeypatch):
    iteration_id = create_manual_iteration("tester-nonzero-artifact", mode="real-cli")
    runner = SequenceRunner([CLIResult(command=[], returncode=1, stdout=make_tester_json(), stderr="cua-driver exited 1")])
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = pipeline._tester_node(
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
    assert len(runner.commands) == 1
    assert any(event["type"] == "tester.nonzero_artifact.accepted" for event in detail["events"])


def test_tester_review_fallback_failure_uses_existing_retry_path(monkeypatch):
    iteration_id = create_manual_iteration("tester-review-fallback-fails", mode="real-cli")
    runner = SequenceRunner(
        [
            CLIResult(command=[], returncode=1, stdout="", stderr="CuaDriver permission denied"),
            CLIResult(command=[], returncode=2, stdout="", stderr="review fallback failed"),
        ]
    )
    monkeypatch.setattr(pipeline, "real_runner", runner)

    result = pipeline._tester_node(
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
    assert "tester.review_fallback.started" in event_types
    assert "tester.review_fallback.failed" in event_types
    assert "tester.max_retries" in event_types


def test_execute_live_cli_node_from_db_current_node():
    iteration_id = create_manual_iteration("live-cli-node", mode="dry-run")
    pipeline.db.update_iteration(iteration_id, current_node="planner", status="planning")
    state = {"iteration_id": iteration_id, "mode": "dry-run", "current_node": None}

    pipeline._execute(state, ["echo", "planner"], node="planner")
    snapshot = pipeline._live_cli_snapshot(iteration_id)
    assert snapshot is not None
    assert snapshot["node"] == "planner"

    pipeline.db.update_iteration(iteration_id, current_node="coder")
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
    pipeline._reset_live_cli(iteration_id, "planner")
    queue = pipeline.broker.subscribe(iteration_id)
    try:
        pipeline._append_live_cli(iteration_id, "stdout", "hello")
        envelope = queue.get(timeout=1)
        assert envelope.type == "cli.output"
        assert envelope.event is not None
        assert envelope.event["payload"]["node"] == "planner"
        assert envelope.event["payload"]["stream"] == "stdout"
        assert envelope.event["payload"]["chunk"] == "hello"
    finally:
        pipeline.broker.unsubscribe(iteration_id, queue)


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
    pipeline.db.update_iteration(iteration_id, current_node="planner", status="planning")
    pipeline.stop_iteration(iteration_id, "stopped for test")
    row = pipeline.db.get_iteration_row(iteration_id)
    assert row["status"] == "stopped"
    assert row["stopped_at_node"] == "planner"


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
    drain_jobs()

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
    drain_jobs()

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
        stopped_at_node="planner",
        last_error="user stopped",
    )
    resume = client.post(f"/api/iterations/{iteration_id}/resume", json={"note": "continue"})
    assert resume.status_code == 200
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert detail["status"] != "stopped"
    assert any(event["type"] == "iteration.resumed" for event in detail["events"])


def test_ui_spec_schema_validates():
    spec = UITestSpec.model_validate(
        {
            "id": "web_smoke",
            "title": "SpecForge smoke",
            "kind": "web",
            "target": {"url": "http://127.0.0.1:5178"},
            "steps": [{"action": "assert_text", "text": "SpecForge"}],
        }
    )
    assert spec.target.chrome_bundle_id == "com.google.Chrome"
    assert spec.steps[0].action == "assert_text"


def test_ui_spec_schema_rejects_unknown_action():
    with pytest.raises(Exception):
        UITestSpec.model_validate(
            {
                "id": "bad",
                "kind": "web",
                "target": {"url": "http://127.0.0.1:5178"},
                "steps": [{"action": "drag_text", "text": "SpecForge"}],
            }
        )


def test_validate_ui_spec_content_rejects_invalid_action():
    with pytest.raises(ValueError, match="invalid UI spec"):
        validate_ui_spec_content(
            "tests/ui/bad.json",
            '{"id":"bad","kind":"web","target":{"url":"http://127.0.0.1:5178"},"steps":[{"action":"click","text":"Go"}]}',
        )


def test_planner_write_rejects_invalid_ui_spec(tmp_path):
    project = post_project(tmp_path, "ui-spec-planner")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ui spec validation", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    docs = IterationDocs(pipeline.docs_root(iteration_id))
    docs.ensure()
    bad_spec = '{"id":"bad","kind":"web","target":{"url":"http://127.0.0.1:5178"},"steps":[{"action":"click","text":"Go"}]}'
    artifact = PlannerArtifact(
        system_design="---\n\n# Design\n",
        modification_plan="---\n\n# Plan\n",
        testing_plan="---\n\n# Tests\n",
        tests=[ArtifactFile(path="tests/ui/bad.json", content=bad_spec)],
    )
    with pytest.raises(ValueError, match="invalid UI spec"):
        pipeline._write_planner_artifact(iteration_id, docs, artifact)


def test_ui_spec_invalid_blocks_tester_with_classified_error(tmp_path, monkeypatch):
    project = post_project(tmp_path, "ui-spec-tester")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "ui spec tester block", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    ui_path = pipeline.docs_root(iteration_id) / "tests" / "ui" / "bad.json"
    ui_path.parent.mkdir(parents=True, exist_ok=True)
    ui_path.write_text(
        '{"id":"bad","kind":"web","target":{"url":"http://127.0.0.1:5178"},"steps":[{"action":"click","text":"Go"}]}',
        encoding="utf-8",
    )
    docs = IterationDocs(pipeline.docs_root(iteration_id))
    pipeline._update_iteration(
        iteration_id,
        test_integrity_baseline=build_test_integrity_manifest(docs.root),
    )

    result = pipeline._tester_node({"iteration_id": iteration_id, "mode": "dry-run"})
    assert result["status"] == "blocked"
    detail = client.get(f"/api/iterations/{iteration_id}").json()
    assert any(event["type"] == "ui_spec.invalid" for event in detail["events"])
    classified = [event for event in detail["events"] if event["type"] == "error.classified"]
    assert classified[-1]["payload"]["title"] == "UI 测试规格无效"


def test_ui_spec_id_must_be_safe_slug():
    with pytest.raises(Exception):
        UITestSpec.model_validate(
            {
                "id": "../bad",
                "kind": "web",
                "target": {"url": "http://127.0.0.1:5178"},
                "steps": [{"action": "assert_text", "text": "SpecForge"}],
            }
        )


def test_ui_recordings_are_not_protected_by_checksum(tmp_path):
    root = tmp_path / "docs"
    protected = root / "tests" / "ui" / "web_smoke.json"
    recording = root / "tests" / "ui" / "recordings" / "web_smoke" / "frame.json"
    protected.parent.mkdir(parents=True)
    recording.parent.mkdir(parents=True)
    protected.write_text('{"id":"web_smoke"}', encoding="utf-8")
    baseline = build_test_integrity_manifest(root)
    recording.write_text('{"ok":true}', encoding="utf-8")
    assert compare_test_integrity(root, baseline) == []


def test_checksum_gate_blocks_modified_protected_tests():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "integrity", "goal": "protect tests", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    test_file = pipeline.docs_root(iteration_id) / "tests" / "unit" / "test_transitions.py"
    test_file.write_text("def test_bad():\n    assert True\n", encoding="utf-8")

    result = pipeline._integrity_check_node({"iteration_id": iteration_id})
    assert result["status"] == "blocked"
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert "modified protected test" in detail.json()["last_error"]
    payload = detail.json()
    classified = [event for event in payload["events"] if event["type"] == "error.classified"]
    assert classified
    assert "受保护测试" in classified[-1]["payload"]["action_hint"]


def test_artifact_invalid_emits_classified_error():
    original_planner = pipeline._planner_artifact

    def bad_planner_artifact(state, run_result):
        raise ValueError("planner returned invalid JSON")

    pipeline._planner_artifact = bad_planner_artifact  # type: ignore[method-assign]
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "invalid-artifact", "goal": "bad planner output", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]

    assert detail["status"] == "blocked"
    assert any(event["type"] == "artifact.invalid" for event in detail["events"])
    classified = [event for event in detail["events"] if event["type"] == "error.classified"]
    assert classified[-1]["payload"]["title"] == "Agent 产物格式无效"
    assert "JSON artifact" in classified[-1]["payload"]["action_hint"]


def test_tester_failure_retries_until_blocked(tmp_path):
    project = post_project(tmp_path, "retry-project", default_mode="dry-run", max_coder_tester_retries=1)
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "force tester failure"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    detail = client.get(f"/api/iterations/{iteration_id}")
    payload = detail.json()
    assert payload["status"] == "blocked"
    assert payload["retry_counts"]["coder_tester"] == 2
    assert "forced tester failure" in payload["last_error"]


def test_ui_driver_playwright_fallback_passes_web():
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("playwright_fallback")
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "ui-playwright", "goal": "run UI playwright", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]
        pipeline.ui_driver = original_ui_driver

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_driver.fallback" for event in detail["events"])
    assert not any(event["type"] == "ui_driver.warning" for event in detail["events"])
    assert detail["ui_results"][0]["status"] == "passed"
    assert detail["ui_results"][0]["driver"] == "playwright"


def test_ui_driver_cua_unavailable_native_warns_web_playwright():
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_and_native_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("mixed_fallback")
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "ui-mixed", "goal": "run UI mixed", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]
        pipeline.ui_driver = original_ui_driver

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_driver.fallback" for event in detail["events"])
    assert any(event["type"] == "ui_driver.warning" for event in detail["events"])
    by_id = {item["id"]: item for item in detail["ui_results"]}
    assert by_id["web_smoke"]["status"] == "passed"
    assert by_id["web_smoke"]["driver"] == "playwright"
    assert by_id["native_smoke"]["status"] == "warning"


def test_ui_driver_playwright_unavailable_web_warns():
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("dual_unavailable")
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "ui-dual-fail", "goal": "run UI dual fail", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]
        pipeline.ui_driver = original_ui_driver

    assert detail["status"] == "awaiting_verify_approval"
    assert any(event["type"] == "ui_driver.warning" for event in detail["events"])
    assert detail["ui_results"][0]["status"] == "warning"


def test_ui_driver_pass_writes_results_and_artifacts():
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("passed")
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "ui-pass", "goal": "run UI pass", "mode": "dry-run"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]
        pipeline.ui_driver = original_ui_driver

    assert detail["status"] == "awaiting_verify_approval"
    assert detail["ui_results"][0]["status"] == "passed"
    assert any(doc["name"] == "ui_report" for doc in detail["documents"])
    assert any(doc["name"] == "ui_results" for doc in detail["documents"])
    assert client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").status_code == 200


def test_ui_driver_failure_warns_without_retry(tmp_path):
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("failed")
    try:
        project = post_project(tmp_path, "ui-fail-project", default_mode="dry-run", max_coder_tester_retries=1)
        project_id = project.json()["id"]
        resp = client.post(
            "/api/iterations",
            json={"project_id": project_id, "goal": "run UI fail"},
        )
        iteration_id = resp.json()["id"]
        drain_jobs()
        detail = client.get(f"/api/iterations/{iteration_id}").json()
    finally:
        pipeline._planner_artifact = original_planner  # type: ignore[method-assign]
        pipeline.ui_driver = original_ui_driver

    assert detail["status"] == "awaiting_verify_approval"
    assert detail["retry_counts"] == {}
    ui_progress = [
        event
        for event in detail["events"]
        if event["type"] == "node.progress" and event["payload"].get("node") == "ui_driver"
    ]
    assert ui_progress[-1]["payload"]["severity"] == "warning"
    assert "非阻断" in ui_progress[-1]["payload"]["message"]
    failed_event = next(event for event in detail["events"] if event["type"] == "ui_driver.failed")
    assert failed_event["payload"]["blocking"] is False
    assert detail["ui_results"][0]["status"] == "failed"
    ui_payload = client.get(f"/api/iterations/{iteration_id}/artifacts/ui_results.json").json()
    assert "UI 自动化测试失败" in ui_payload["warnings"][0]


def planner_with_ui_spec(state, run_result):
    goal = state["goal"]
    ui_spec = (
        '{"id":"web_smoke","title":"SpecForge smoke","kind":"web",'
        '"target":{"url":"http://127.0.0.1:5178"},'
        '"steps":[{"action":"assert_text","text":"SpecForge"}]}'
    )
    return PlannerArtifact(
        system_design=f"# Design\n\n{goal}",
        modification_plan="# Plan\n\n- Ship UI smoke.",
        testing_plan="# Tests\n\n- UI smoke.",
        tests=[
            ArtifactFile(path="tests/unit/test_transitions.py", content="def test_ok():\n    assert True\n"),
            ArtifactFile(path="tests/ui/web_smoke.json", content=ui_spec),
        ],
    )


def planner_with_ui_and_native_spec(state, run_result):
    goal = state["goal"]
    web_spec = (
        '{"id":"web_smoke","title":"SpecForge smoke","kind":"web",'
        '"target":{"url":"http://127.0.0.1:5178"},'
        '"steps":[{"action":"assert_text","text":"SpecForge"}]}'
    )
    native_spec = (
        '{"id":"native_smoke","title":"Native smoke","kind":"native",'
        '"target":{"bundle_id":"com.example.app"},'
        '"steps":[{"action":"assert_text","text":"Example"}]}'
    )
    return PlannerArtifact(
        system_design=f"# Design\n\n{goal}",
        modification_plan="# Plan\n\n- Ship UI smoke.",
        testing_plan="# Tests\n\n- UI smoke.",
        tests=[
            ArtifactFile(path="tests/unit/test_transitions.py", content="def test_ok():\n    assert True\n"),
            ArtifactFile(path="tests/ui/web_smoke.json", content=web_spec),
            ArtifactFile(path="tests/ui/native_smoke.json", content=native_spec),
        ],
    )


class FakeUIDriver:
    def __init__(self, status: str) -> None:
        self.status = status
        self.last_specs: list[UITestSpec] = []

    def run_specs(self, specs: list[UITestSpec], docs_root):
        self.last_specs = specs
        if self.status == "playwright_fallback":
            return UIDriverRunResult(
                available=True,
                fallback="playwright",
                results=[
                    UITestResult(
                        id=specs[0].id,
                        title=specs[0].title,
                        kind=specs[0].kind,
                        status="passed",
                        target=specs[0].target.url or "",
                        driver="playwright",
                        observations=["找到文本: SpecForge"],
                    )
                ],
            )
        if self.status == "mixed_fallback":
            web = next(spec for spec in specs if spec.kind == "web")
            native = next(spec for spec in specs if spec.kind == "native")
            return UIDriverRunResult(
                available=True,
                fallback="playwright",
                warning="CuaDriver unavailable for native UI",
                results=[
                    UITestResult(
                        id=web.id,
                        title=web.title,
                        kind=web.kind,
                        status="passed",
                        target=web.target.url or "",
                        driver="playwright",
                        observations=["找到文本: SpecForge"],
                    ),
                    UITestResult(
                        id=native.id,
                        title=native.title,
                        kind=native.kind,
                        status="warning",
                        target=native.target.bundle_id or "",
                        driver="cua",
                        error="CuaDriver unavailable for native UI",
                    ),
                ],
            )
        if self.status == "dual_unavailable":
            return UIDriverRunResult(
                available=False,
                warning="CuaDriver missing permissions; Playwright is not installed",
                results=[
                    UITestResult(
                        id=specs[0].id,
                        title=specs[0].title,
                        kind=specs[0].kind,
                        status="warning",
                        target=specs[0].target.url or "",
                        driver="playwright",
                        error="CuaDriver missing permissions; Playwright is not installed",
                    )
                ],
            )
        if self.status == "warning":
            return UIDriverRunResult(
                available=False,
                warning="CuaDriver missing permissions",
                results=[
                    UITestResult(
                        id=specs[0].id,
                        title=specs[0].title,
                        kind=specs[0].kind,
                        status="warning",
                        target=specs[0].target.url or "",
                        error="CuaDriver missing permissions",
                    )
                ],
            )
        if self.status == "failed":
            return UIDriverRunResult(
                available=True,
                results=[
                    UITestResult(
                        id=specs[0].id,
                        title=specs[0].title,
                        kind=specs[0].kind,
                        status="failed",
                        target=specs[0].target.url or "",
                        driver="cua",
                        error="SpecForge text not found",
                    )
                ],
            )
        return UIDriverRunResult(
            available=True,
            results=[
                UITestResult(
                    id=specs[0].id,
                    title=specs[0].title,
                    kind=specs[0].kind,
                    status="passed",
                    target=specs[0].target.url or "",
                    driver="cua",
                    observations=["找到文本: SpecForge"],
                )
            ],
        )
