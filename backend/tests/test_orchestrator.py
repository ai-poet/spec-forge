from fastapi.testclient import TestClient

from specforge.main import app


client = TestClient(app)


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

    filtered = client.get(f"/api/iterations?project_id={project_id}")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["project_id"] == project_id


def test_create_iteration_runs_dry_flow():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo", "goal": "ship a dashboard", "mode": "dry-run"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "awaiting_design_approval"


def test_iteration_detail_includes_documents():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo2", "goal": "make a thing", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]
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

    after_design = client.post(f"/api/iterations/{iteration_id}/approve-design", json={"note": "ok"})
    assert after_design.status_code == 200
    assert after_design.json()["status"] == "awaiting_verify_approval"

    after_verify = client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "ok"})
    assert after_verify.status_code == 200
    assert after_verify.json()["status"] == "delivered"


def test_invalid_approval_returns_409():
    resp = client.post(
        "/api/iterations",
        json={"project_name": "demo4", "goal": "reject early verify", "mode": "dry-run"},
    )
    iteration_id = resp.json()["id"]

    invalid = client.post(f"/api/iterations/{iteration_id}/approve-verify", json={"note": "too early"})
    assert invalid.status_code == 409
