from __future__ import annotations

from pathlib import Path

from specforge.agents.prompt_loader import compose_stage_prompt
from specforge.context_profiles import (
    create_project_profile,
    context_metadata_for_stage,
    context_package_for_run,
    list_project_profiles,
    load_profile_bindings,
    save_profile_bindings,
    workflow_snapshot,
)
from specforge.policy.context_manifest import ManifestLine, write_jsonl
from specforge.storage.db import Database


def test_project_profile_crud_and_bindings(tmp_path):
    profile = create_project_profile(
        tmp_path,
        name="Coder Guide",
        summary="Coder local context",
        stage="coder",
        content="Prefer small focused patches.",
    )

    profiles = list_project_profiles(tmp_path)
    bindings = save_profile_bindings(tmp_path, {"coder": profile.id})

    assert profiles[0].id == profile.id
    assert profiles[0].path.startswith(".specforge/context/profiles/")
    assert bindings["coder"] == profile.id
    assert load_profile_bindings(tmp_path)["coder"] == profile.id


def test_stage_prompt_includes_project_profile_before_project_extra(tmp_path):
    create_project_profile(
        tmp_path,
        name="Coder Guide",
        summary="Coder local context",
        stage="coder",
        content="PROFILE_CONTENT_MARKER",
    )
    profile = list_project_profiles(tmp_path)[0]
    save_profile_bindings(tmp_path, {"coder": profile.id})
    extra = tmp_path / ".specforge" / "skills" / "coder" / "extra.md"
    extra.parent.mkdir(parents=True)
    extra.write_text("EXTRA_MARKER", encoding="utf-8")

    text = compose_stage_prompt(
        "coder",
        repo_root=tmp_path,
        variables={
            "docs_root": "/tmp/iter",
            "schema_hint": "{}",
            "failure_notes": "(none)",
            "framework_conventions": "",
            "convention_excerpt": "",
            "context_manifest": "",
            "runtime_notes": "",
        },
    )

    assert "PROFILE_CONTENT_MARKER" in text
    assert text.index("PROFILE_CONTENT_MARKER") < text.index("EXTRA_MARKER")


def test_workflow_snapshot_includes_policy_provider_and_profile(tmp_path):
    profile = create_project_profile(tmp_path, name="Tester", summary="", stage="code_tester", content="test")
    save_profile_bindings(tmp_path, {"code_tester": profile.id})
    project = {
        "id": "proj_1",
        "root_path": str(tmp_path),
        "cli_bindings": '{"coder":"codex","code_tester":"claude"}',
        "max_coder_tester_retries": 5,
        "max_tester_self_retries": 3,
        "max_clarifications": 2,
        "max_verify_rejects": 1,
        "max_discovery_rounds": 8,
    }

    snapshot = workflow_snapshot(project=project)
    coder = next(node for node in snapshot["nodes"] if node["id"] == "coder")
    tester = next(node for node in snapshot["nodes"] if node["id"] == "code_tester")

    assert snapshot["kind"] == "specforge-fixed-pipeline"
    assert coder["provider"] == "codex"
    assert tester["profile"]["id"] == profile.id
    assert snapshot["retry_budget"]["coder_tester"] == 5


def test_context_package_and_metadata_include_hot_cold_runtime_feedback(tmp_path):
    docs_root = tmp_path / "docs" / "iteration_001"
    docs_root.mkdir(parents=True)
    prd = docs_root / "prd.md"
    prd.write_text("PRD body", encoding="utf-8")
    manifest = docs_root / "context" / "for_coder.jsonl"
    write_jsonl(manifest, [ManifestLine(file="src/app.py", reason="edit target", summary="App")])
    runtime_notes = docs_root / "context" / "runtime_notes.jsonl"
    runtime_notes.parent.mkdir(parents=True, exist_ok=True)
    runtime_notes.write_text('{"note":"Prefer simple UI","node":"coder"}\n', encoding="utf-8")
    profile = create_project_profile(tmp_path, name="Coder", summary="", stage="coder", content="profile")
    save_profile_bindings(tmp_path, {"coder": profile.id})
    documents = [{"name": "prd", "path": str(prd)}]
    events = [
        {
            "type": "provider.continue_fallback",
            "payload": '{"node":"coder","reason":"missing session"}',
            "created_at": "2026-06-05T00:00:00Z",
        }
    ]
    run = {"id": "run_1", "node": "coder"}

    package = context_package_for_run(
        project_root=tmp_path,
        iteration_root=tmp_path / ".specforge" / "iterations" / "iter_1",
        docs_root=docs_root,
        run=run,
        documents=documents,
        events=events,
    )
    metadata = context_metadata_for_stage(tmp_path, docs_root, "coder", previous_feedback="retry")

    assert package["profile"]["id"] == profile.id
    assert package["hot_docs"][0]["preview"] == "PRD body"
    assert package["cold_manifest"][0]["file"] == "src/app.py"
    assert package["runtime_notes"][0]["note"] == "Prefer simple UI"
    assert package["previous_feedback"][0]["message"] == "missing session"
    assert metadata["previous_feedback"] == "retry"


def test_context_api_smoke(tmp_path):
    from fastapi.testclient import TestClient
    import specforge.main as main

    db = Database(tmp_path / "db.sqlite3")
    db.init()
    project_id = db.create_project(root_path=str(tmp_path / "repo"), create_if_missing=True, name="repo", default_mode="dry-run")
    project = db.get_project_row(project_id)
    assert project is not None
    profile = create_project_profile(Path(project["root_path"]), name="Coder", summary="", stage="coder", content="profile")
    save_profile_bindings(Path(project["root_path"]), {"coder": profile.id})

    main.db = db
    main.pipeline.db = db
    client = TestClient(main.app)

    profiles = client.get(f"/api/projects/{project_id}/profiles")
    bindings = client.get(f"/api/projects/{project_id}/profile-bindings")

    assert profiles.status_code == 200
    assert profiles.json()[0]["id"] == profile.id
    assert bindings.json()["bindings"]["coder"] == profile.id
