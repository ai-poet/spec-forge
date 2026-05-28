from fastapi.testclient import TestClient

from specforge.contracts import PlannerArtifact, parse_json_artifact
from specforge.main import app, job_queue, pipeline


client = TestClient(app)


def drain_jobs():
    job_queue.join()


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_project_and_filter_iterations():
    project = client.post("/api/projects", json={"name": "project-a", "description": "demo"})
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


def test_create_epic_and_attach_iteration():
    project = client.post("/api/projects", json={"name": "epic-project", "description": "demo"})
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


def test_epic_status_delivered_after_all_iterations_deliver():
    project = client.post("/api/projects", json={"name": "epic-delivered"})
    project_id = project.json()["id"]
    epic = client.post("/api/epics", json={"project_id": project_id, "title": "Deliver all"})
    epic_id = epic.json()["id"]

    resp = client.post("/api/iterations", json={"project_id": project_id, "epic_id": epic_id, "goal": "ship", "mode": "dry-run"})
    iteration_id = resp.json()["id"]
    drain_jobs()
    client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
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
    assert detail.json()["status"] == "awaiting_design_approval"


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

    after_design = client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
    assert after_design.status_code == 200
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

    client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
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

    invalid = client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "too early"})
    assert invalid.status_code == 409


def test_project_config_is_inherited():
    project = client.post(
        "/api/projects",
        json={
            "name": "configured",
            "default_mode": "dry-run",
            "default_test_command": "pytest",
            "max_coder_tester_retries": 2,
        },
    )
    assert project.status_code == 200
    project_id = project.json()["id"]

    update = client.patch(f"/api/projects/{project_id}", json={"tester_model": "gpt-test"})
    assert update.status_code == 200
    assert update.json()["tester_model"] == "gpt-test"

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


def test_checksum_gate_blocks_modified_protected_tests():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "integrity", "goal": "protect tests", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    test_file = pipeline.docs_root(iteration_id) / "tests" / "unit" / "test_transitions.py"
    test_file.write_text("def test_bad():\n    assert True\n", encoding="utf-8")

    after_design = client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
    assert after_design.status_code == 200
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}")
    assert detail.json()["status"] == "blocked"
    assert "modified protected test" in detail.json()["last_error"]


def test_tester_failure_retries_until_blocked():
    project = client.post(
        "/api/projects",
        json={"name": "retry-project", "default_mode": "dry-run", "max_coder_tester_retries": 1},
    )
    project_id = project.json()["id"]
    resp = client.post(
        "/api/iterations",
        json={"project_id": project_id, "goal": "force tester failure"},
    )
    iteration_id = resp.json()["id"]
    drain_jobs()

    after_design = client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
    assert after_design.status_code == 200
    drain_jobs()
    detail = client.get(f"/api/iterations/{iteration_id}")
    payload = detail.json()
    assert payload["status"] == "blocked"
    assert payload["retry_counts"]["coder_tester"] == 2
    assert "forced tester failure" in payload["last_error"]
