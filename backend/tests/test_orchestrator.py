import sys
import time
import pytest
from pathlib import Path
from threading import Thread
from fastapi.testclient import TestClient

from specforge import contracts as contract_models
from specforge.contracts import ArtifactFile, PlannerArtifact, UIDriverRunResult, UITestResult, UITestSpec, parse_json_artifact
from specforge.docs_io import compare_test_integrity, test_integrity_manifest as build_test_integrity_manifest
from specforge.main import app, job_queue, pipeline


client = TestClient(app)


def post_project(tmp_path, name: str, **extra):
    root = tmp_path / name
    root.mkdir()
    payload = {"root_path": str(root), "create_if_missing": False, "name": name, **extra}
    return client.post("/api/projects", json=payload)


def drain_jobs():
    job_queue.join()


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
    assert str(workspace).startswith(str((Path(root_path) / ".specforge" / "iterations").resolve()))
    assert (workspace / "docs" / "system_design.md").exists()


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


def test_native_cli_events_are_presented_as_semantic_progress():
    event = pipeline._present_native_cli_event({"type": "item.started", "item": {"type": "command_execution", "command": ["pytest", "-q"]}})
    assert event
    assert event["title"] == "Codex 命令执行开始"
    assert "pytest -q" in event["message"]


def test_execute_live_cli_node_from_db_current_node():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "live-cli-node", "goal": "check live_cli node", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
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
    iteration_id = "stop-cli"
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
    pipeline.db.update_iteration(iteration_id, current_node="planner", status="planning")
    pipeline.stop_iteration(iteration_id, "stopped for test")
    row = pipeline.db.get_iteration_row(iteration_id)
    assert row["status"] == "stopped"
    assert row["stopped_at_node"] == "planner"


def test_resume_stopped_iteration(tmp_path):
    project = post_project(tmp_path, "resume-stopped")
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "resume after stop", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
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


def test_ui_driver_unavailable_warns_and_continues():
    original_planner = pipeline._planner_artifact
    original_ui_driver = pipeline.ui_driver
    pipeline._planner_artifact = planner_with_ui_spec  # type: ignore[method-assign]
    pipeline.ui_driver = FakeUIDriver("warning")
    try:
        resp = client.post(
            "/api/iterations",
            json={"project_name": "ui-warning", "goal": "run UI warning", "mode": "dry-run"},
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


def test_ui_driver_failure_retries_until_blocked(tmp_path):
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

    assert detail["status"] == "blocked"
    assert detail["retry_counts"]["coder_tester"] == 2
    assert any(event["type"] == "ui_driver.failed" for event in detail["events"])


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


class FakeUIDriver:
    def __init__(self, status: str) -> None:
        self.status = status
        self.last_specs: list[UITestSpec] = []

    def run_specs(self, specs: list[UITestSpec], docs_root):
        self.last_specs = specs
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
                    observations=["找到文本: SpecForge"],
                )
            ],
        )
