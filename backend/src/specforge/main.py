from __future__ import annotations

from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from queue import Empty
from typing import Optional

import asyncio

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from specforge.agents.cli_commands import parse_cli_bindings, serialize_cli_bindings
from specforge.agents.cli_runner import DryRunRunner, RealCLIRunner
from specforge.core.config import settings
from specforge.storage.db import Database
from specforge.runtime.events import EventBroker, EventEnvelope
from specforge.runtime.job_queue import PipelineJobQueue
from specforge.core.models import (
    AnswerRequirementsRequest,
    ApproveRequest,
    CreateEpicRequest,
    CreateIterationRequest,
    CreateProjectRequest,
    DiscoveryHistoryEntry,
    EpicDetail,
    EpicSummary,
    IterationDetail,
    IterationSummary,
    PendingDiscovery,
    ProfileBindingsRequest,
    ProfileBindingsResponse,
    ProjectProfile,
    ProjectProfileRequest,
    ProjectSummary,
    RetryRequest,
    LogSummaryResponse,
    WorkflowSnapshot,
    ContextPackage,
    ManualSkipRequest,
    UpdateEpicRequest,
    UpdateProjectRequest,
    CliBindings,
    CliProviderName,
    ValidateProjectPathRequest,
    BrowseDirectoryResponse,
    PickFolderResponse,
)
from specforge.context_profiles import (
    create_project_profile,
    delete_project_profile,
    list_project_profiles,
    load_profile_bindings,
    save_profile_bindings,
    update_project_profile,
)
from specforge.pipeline import LangGraphPipeline
from specforge.documents.docs_scaffold import ensure_project_docs
from specforge.ui.ui_runtime import fast_ui_runtime_status, log_fast_ui_runtime_status
from specforge.ui.native_dialog import pick_folder, resolve_picked_folder
from specforge.documents.project_paths import ProjectPathError, browse_directory, prepare_project_root, validate_project_root
from specforge.environment import environment_checks


db = Database(settings.db_path)
db.init()


def make_runner():
    if settings.mode == "real-cli":
        return RealCLIRunner(registry_path=settings.active_cli_registry_path)
    return DryRunRunner()


broker = EventBroker()
pipeline = LangGraphPipeline(db=db, runner=make_runner(), broker=broker)
job_queue = PipelineJobQueue(pipeline)
job_queue.start()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.backend_cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    db.init()
    job_queue.start()
    pipeline.recover_interrupted_iterations(job_queue)
    log_fast_ui_runtime_status()


@app.on_event("shutdown")
def on_shutdown() -> None:
    pipeline.shutdown()


@app.get("/api/health")
def health() -> dict[str, object]:
    ui = fast_ui_runtime_status()
    return {
        "status": "ok",
        "langgraph": {
            "version": package_version("langgraph"),
            "checkpoint_db": str(settings.langgraph_db_path),
            "checkpoint_db_exists": settings.langgraph_db_path.exists(),
            "checkpoint_db_bytes": settings.langgraph_db_path.stat().st_size if settings.langgraph_db_path.exists() else 0,
        },
        "ui": {
            "playwright": ui["playwright"],
            "cua": ui["cua"],
            "cua_session": ui["cua_session"],
            "playwright_install_hint": ui["playwright_install_hint"],
            "cua_install_hint": ui["cua_install_hint"],
        },
        "ui_install_hint": ui["install_hint"],
    }


def package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


@app.get("/api/environment/checks")
def get_environment_checks() -> dict[str, object]:
    return environment_checks()


@app.get("/api/projects", response_model=list[ProjectSummary])
def list_projects() -> list[ProjectSummary]:
    iterations = db.list_iterations()
    counts: dict[str, dict[str, int]] = {}
    for iteration in iterations:
        project_id = iteration["project_id"] or ""
        bucket = counts.setdefault(project_id, {"total": 0, "active": 0, "delivered": 0})
        bucket["total"] += 1
        if iteration["status"] == "delivered":
            bucket["delivered"] += 1
        elif iteration["status"] not in {"blocked", "blocked_user", "failed", "stopped"}:
            bucket["active"] += 1
    items = []
    for row in db.list_projects():
        bucket = counts.get(row["id"], {"total": 0, "active": 0, "delivered": 0})
        items.append(
            project_summary(row, bucket)
        )
    return items


@app.post("/api/projects/validate-path")
def validate_path(payload: ValidateProjectPathRequest) -> dict[str, str | bool]:
    return validate_project_root(payload.root_path, payload.create_if_missing)


@app.get("/api/projects/browse", response_model=BrowseDirectoryResponse)
def browse_projects(path: Optional[str] = Query(default=None)) -> BrowseDirectoryResponse:
    try:
        payload = browse_directory(path)
    except ProjectPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BrowseDirectoryResponse.model_validate(payload)


@app.post("/api/projects/pick-folder", response_model=PickFolderResponse)
def pick_project_folder() -> PickFolderResponse:
    selected = pick_folder(prompt="选择项目文件夹")
    if not selected:
        return PickFolderResponse(cancelled=True, path="")
    try:
        resolved = resolve_picked_folder(selected)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"invalid folder: {exc}") from exc
    return PickFolderResponse(cancelled=False, path=resolved)


@app.post("/api/projects", response_model=ProjectSummary)
def create_project(payload: CreateProjectRequest) -> ProjectSummary:
    try:
        resolved = prepare_project_root(payload.root_path, payload.create_if_missing)
    except ProjectPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resolved_str = str(resolved)
    if db.get_project_by_root_path(resolved_str) is not None:
        raise HTTPException(status_code=409, detail="project already registered for this folder")
    display_name = payload.name or resolved.name
    try:
        project_id = db.create_project(
            root_path=resolved_str,
            create_if_missing=False,
            name=display_name,
            description=payload.description,
            default_mode=payload.default_mode.value,
            default_test_command=payload.default_test_command,
            default_build_command=payload.default_build_command,
            max_coder_tester_retries=payload.max_coder_tester_retries,
            max_clarifications=payload.max_clarifications,
            max_verify_rejects=payload.max_verify_rejects,
            max_tester_self_retries=payload.max_tester_self_retries,
            max_discovery_rounds=payload.max_discovery_rounds,
        )
    except ValueError as exc:
        message = str(exc)
        if "root_path" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc
    ensure_project_docs(resolved, project_name=display_name, description=payload.description)
    row = db.get_project_row(project_id)
    assert row is not None
    return project_summary(row)


@app.get("/api/projects/{project_id}", response_model=ProjectSummary)
def get_project(project_id: str) -> ProjectSummary:
    row = db.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    counts = project_counts(project_id)
    return project_summary(row, counts)


@app.patch("/api/projects/{project_id}", response_model=ProjectSummary)
def update_project(project_id: str, payload: UpdateProjectRequest) -> ProjectSummary:
    row = db.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    data = payload.model_dump(exclude_unset=True)
    create_if_missing = bool(data.pop("create_if_missing", False))
    if "root_path" in data and data["root_path"] is not None:
        try:
            resolved = prepare_project_root(data["root_path"], create_if_missing)
        except ProjectPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        resolved_str = str(resolved)
        existing = db.get_project_by_root_path(resolved_str)
        if existing is not None and existing["id"] != project_id:
            raise HTTPException(status_code=409, detail="project already registered for this folder")
        data["root_path"] = resolved_str
    if "default_mode" in data and data["default_mode"] is not None:
        data["default_mode"] = data["default_mode"].value
    if "cli_bindings" in data:
        bindings = data.pop("cli_bindings")
        if bindings is None:
            data["cli_bindings"] = None
        else:
            dumped = bindings.model_dump() if isinstance(bindings, CliBindings) else bindings
            normalized = {
                key: (value.value if hasattr(value, "value") else value)
                for key, value in dumped.items()
            }
            data["cli_bindings"] = serialize_cli_bindings(normalized)
    db.update_project(project_id, **data)
    updated = db.get_project_row(project_id)
    assert updated is not None
    return project_summary(updated, project_counts(project_id))


def _project_root_or_404(project_id: str) -> Path:
    row = db.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not row["root_path"]:
        raise HTTPException(status_code=404, detail="project root not bound")
    return Path(row["root_path"])


@app.get("/api/projects/{project_id}/profiles", response_model=list[ProjectProfile])
def get_project_profiles(project_id: str) -> list[ProjectProfile]:
    root = _project_root_or_404(project_id)
    return [ProjectProfile(**profile.payload()) for profile in list_project_profiles(root)]


@app.post("/api/projects/{project_id}/profiles", response_model=ProjectProfile)
def create_profile(project_id: str, payload: ProjectProfileRequest) -> ProjectProfile:
    root = _project_root_or_404(project_id)
    try:
        profile = create_project_profile(
            root,
            name=payload.name,
            summary=payload.summary,
            stage=payload.stage,
            content=payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProjectProfile(**profile.payload())


@app.patch("/api/projects/{project_id}/profiles/{profile_id}", response_model=ProjectProfile)
def update_profile(project_id: str, profile_id: str, payload: ProjectProfileRequest) -> ProjectProfile:
    root = _project_root_or_404(project_id)
    try:
        profile = update_project_profile(
            root,
            profile_id,
            name=payload.name,
            summary=payload.summary,
            stage=payload.stage,
            content=payload.content,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="profile not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProjectProfile(**profile.payload())


@app.delete("/api/projects/{project_id}/profiles/{profile_id}")
def delete_profile(project_id: str, profile_id: str) -> dict[str, bool]:
    root = _project_root_or_404(project_id)
    if not delete_project_profile(root, profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    return {"ok": True}


@app.get("/api/projects/{project_id}/profile-bindings", response_model=ProfileBindingsResponse)
def get_profile_bindings(project_id: str) -> ProfileBindingsResponse:
    root = _project_root_or_404(project_id)
    return ProfileBindingsResponse(bindings=load_profile_bindings(root))


@app.patch("/api/projects/{project_id}/profile-bindings", response_model=ProfileBindingsResponse)
def patch_profile_bindings(project_id: str, payload: ProfileBindingsRequest) -> ProfileBindingsResponse:
    root = _project_root_or_404(project_id)
    try:
        bindings = save_profile_bindings(root, payload.bindings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProfileBindingsResponse(bindings=bindings)


_TERMINAL_ITERATION_STATUSES = {"delivered", "blocked", "blocked_user", "failed", "stopped"}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    row = db.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    iterations = db.list_iterations(project_id=project_id)
    for iteration in iterations:
        pipeline.cancel_cli(iteration["id"])
        if iteration["status"] not in _TERMINAL_ITERATION_STATUSES:
            pipeline.stop_iteration(iteration["id"], "project deleted")
    if not db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    for iteration in iterations:
        pipeline.forget_iteration_state(iteration["id"])
    return {"ok": True}


@app.get("/api/epics", response_model=list[EpicSummary])
def list_epics(project_id: str = Query()) -> list[EpicSummary]:
    if db.get_project_row(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return [epic_summary(row) for row in db.list_epics(project_id)]


@app.post("/api/epics", response_model=EpicSummary)
def create_epic(payload: CreateEpicRequest) -> EpicSummary:
    if db.get_project_row(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    epic_id = db.create_epic(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        acceptance_criteria=payload.acceptance_criteria,
    )
    row = db.get_epic_row(epic_id)
    assert row is not None
    return epic_summary(row)


@app.get("/api/epics/{epic_id}", response_model=EpicDetail)
def get_epic(epic_id: str) -> EpicDetail:
    row = db.get_epic_row(epic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="epic not found")
    return epic_detail(row)


@app.patch("/api/epics/{epic_id}", response_model=EpicSummary)
def update_epic(epic_id: str, payload: UpdateEpicRequest) -> EpicSummary:
    row = db.get_epic_row(epic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="epic not found")
    db.update_epic(epic_id, **payload.model_dump(exclude_unset=True))
    updated = db.get_epic_row(epic_id)
    assert updated is not None
    return epic_summary(updated)


@app.delete("/api/epics/{epic_id}")
def delete_epic(epic_id: str) -> dict[str, bool]:
    row = db.get_epic_row(epic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="epic not found")
    iterations = db.list_iterations(epic_id=epic_id)
    for iteration in iterations:
        pipeline.cancel_cli(iteration["id"])
        if iteration["status"] not in _TERMINAL_ITERATION_STATUSES:
            pipeline.stop_iteration(iteration["id"], "epic deleted")
    if not db.delete_epic(epic_id):
        raise HTTPException(status_code=404, detail="epic not found")
    for iteration in iterations:
        pipeline.forget_iteration_state(iteration["id"])
    return {"ok": True}


@app.get("/api/iterations", response_model=list[IterationSummary])
def list_iterations(project_id: Optional[str] = Query(default=None), epic_id: Optional[str] = Query(default=None)) -> list[IterationSummary]:
    items = []
    for row in db.list_iterations(project_id=project_id, epic_id=epic_id):
        items.append(iteration_summary(row))
    return items


@app.post("/api/iterations", response_model=IterationSummary)
def create_iteration(payload: CreateIterationRequest) -> IterationSummary:
    project_name = payload.project_name
    if payload.project_id:
        project = db.get_project_row(payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        project_name = project["name"]
    if payload.epic_id:
        epic = db.get_epic_row(payload.epic_id)
        if epic is None:
            raise HTTPException(status_code=404, detail="epic not found")
        if payload.project_id and epic["project_id"] != payload.project_id:
            raise HTTPException(status_code=422, detail="epic does not belong to project")
        existing = db.list_iterations(epic_id=payload.epic_id)
        if existing:
            raise HTTPException(status_code=409, detail="epic already has a pipeline")
    if not project_name:
        raise HTTPException(status_code=422, detail="project_name or project_id is required")
    iteration_id = db.create_iteration(
        project_name=project_name,
        project_id=payload.project_id,
        goal=payload.goal,
        mode=payload.mode.value if payload.mode else None,
        test_command=payload.test_command,
        build_command=payload.build_command,
        epic_id=payload.epic_id,
    )
    db.update_iteration(iteration_id, status="queued", current_node=None)
    db.add_event(iteration_id, event_type="iteration.queued", payload={"job": "start"})
    broker.publish(iteration_id, EventEnvelope(type="snapshot", snapshot=pipeline.dashboard_snapshot(iteration_id)))
    job_queue.enqueue_start(iteration_id)
    row = db.get_iteration_row(iteration_id)
    assert row is not None
    if row["epic_id"]:
        db.update_epic_status(row["epic_id"])
    return iteration_summary(row)


@app.get("/api/iterations/{iteration_id}", response_model=IterationDetail)
def get_iteration(iteration_id: str) -> IterationDetail:
    row = db.get_iteration_row(iteration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="iteration not found")
    snapshot = pipeline.dashboard_snapshot(iteration_id)
    return IterationDetail(
        id=snapshot["id"],
        project_id=snapshot["project_id"],
        epic_id=snapshot["epic_id"],
        project_name=snapshot["project_name"],
        goal=snapshot["goal"],
        mode=snapshot["mode"],
        status=snapshot["status"],
        current_node=snapshot["current_node"],
        stopped_at_node=snapshot.get("stopped_at_node"),
        retry_counts=snapshot["retry_counts"],
        last_error=snapshot["last_error"],
        created_at=snapshot["created_at"],
        updated_at=snapshot["updated_at"],
        test_command=snapshot["test_command"],
        graph_next=snapshot["graph_next"],
        documents=snapshot["documents"],
        events=snapshot["events"],
        runs=snapshot["runs"],
        ui_results=snapshot["ui_results"],
        live_cli=snapshot.get("live_cli"),
        pending_discovery=PendingDiscovery(**snapshot["pending_discovery"]) if snapshot.get("pending_discovery") else None,
        discovery_history=[DiscoveryHistoryEntry(**item) for item in snapshot.get("discovery_history") or []],
    )


@app.delete("/api/iterations/{iteration_id}")
def delete_iteration(iteration_id: str) -> dict[str, bool]:
    row = db.get_iteration_row(iteration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="iteration not found")
    epic_id = row["epic_id"]
    pipeline.cancel_cli(iteration_id)
    if row["status"] not in _TERMINAL_ITERATION_STATUSES:
        pipeline.stop_iteration(iteration_id, "iteration deleted")
    if not db.delete_iteration(iteration_id):
        raise HTTPException(status_code=404, detail="iteration not found")
    pipeline.forget_iteration_state(iteration_id)
    if epic_id:
        db.update_epic_status(epic_id)
    return {"ok": True}


@app.post("/api/iterations/{iteration_id}/answer-requirements", response_model=IterationDetail)
def answer_requirements(iteration_id: str, payload: AnswerRequirementsRequest) -> IterationDetail:
    if not pipeline.can_resume(iteration_id, "requirements_input"):
        raise HTTPException(status_code=409, detail="iteration is not awaiting requirements_input")
    db.add_event(iteration_id, event_type="resume.queued", payload={"checkpoint": "requirements_input"})
    job_queue.enqueue_resume(iteration_id, "requirements_input", payload.answer)
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/skip-discovery", response_model=IterationDetail)
def skip_discovery(iteration_id: str, payload: ApproveRequest) -> IterationDetail:
    if not pipeline.can_resume(iteration_id, "requirements_input"):
        raise HTTPException(status_code=409, detail="iteration is not awaiting requirements_input")
    note = payload.note or "proceed with documented assumptions"
    db.add_event(iteration_id, event_type="resume.queued", payload={"checkpoint": "requirements_input", "skip": True})
    job_queue.enqueue_resume(iteration_id, "requirements_input", f"SKIP:{note}")
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/approve-verify", response_model=IterationSummary)
def approve_verify(iteration_id: str, payload: ApproveRequest) -> IterationSummary:
    if not pipeline.can_resume(iteration_id, "verify_approval"):
        raise HTTPException(status_code=409, detail="iteration is not awaiting verify_approval")
    db.add_event(iteration_id, event_type="resume.queued", payload={"checkpoint": "verify_approval"})
    job_queue.enqueue_resume(iteration_id, "verify_approval", payload.note)
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/retry", response_model=IterationSummary)
def retry_iteration(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    pipeline.retry(iteration_id, note=payload.note)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/stop", response_model=IterationSummary)
def stop_iteration(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    pipeline.stop_iteration(iteration_id, reason=payload.note or "stopped")
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/resume", response_model=IterationSummary)
def resume_iteration(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    if not pipeline.can_resume_stopped(iteration_id):
        raise HTTPException(status_code=409, detail="iteration is not resumable")
    db.add_event(iteration_id, event_type="resume.queued", payload={"kind": "stopped"})
    job_queue.enqueue_resume_stopped(iteration_id, payload.note)
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/manual-skip", response_model=IterationSummary)
def manual_skip_iteration(iteration_id: str, payload: ManualSkipRequest) -> IterationSummary:
    try:
        node = pipeline.prepare_manual_skip(iteration_id, payload.node, payload.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="iteration not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job_queue.enqueue_manual_skip(iteration_id, node, payload.note)
    refresh_iteration_epic(iteration_id)
    return get_iteration(iteration_id)


_RUNTIME_NOTE_STATUSES = {"planning", "coding", "testing", "retrying", "queued", "stopped"}


@app.post("/api/iterations/{iteration_id}/runtime-note", response_model=IterationSummary)
def add_runtime_note(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    iteration = db.get_iteration_row(iteration_id)
    if not iteration:
        raise HTTPException(status_code=404, detail="iteration not found")
    if iteration["status"] not in _RUNTIME_NOTE_STATUSES:
        raise HTTPException(status_code=409, detail="iteration is not accepting runtime notes")
    note = (payload.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="note is required")
    node = iteration["current_node"] if "current_node" in iteration.keys() else None
    if not node and "stopped_at_node" in iteration.keys():
        node = iteration["stopped_at_node"]
    pipeline.add_runtime_note(iteration_id, note, node=str(node or "user"))
    return get_iteration(iteration_id)


@app.get("/api/iterations/{iteration_id}/documents/{name}")
def get_document(iteration_id: str, name: str) -> dict[str, str]:
    docs = db.list_documents(iteration_id)
    for doc in docs:
        if doc["name"] == name:
            from pathlib import Path

            path = Path(doc["path"])
            if not path.exists():
                raise HTTPException(status_code=404, detail="document file not found")
            return {"name": name, "content": path.read_text(encoding="utf-8"), "checksum": doc["checksum"]}
    raise HTTPException(status_code=404, detail="document not found")


@app.get("/api/iterations/{iteration_id}/artifacts/{artifact_path:path}")
def get_artifact(iteration_id: str, artifact_path: str):
    if db.get_iteration_row(iteration_id) is None:
        raise HTTPException(status_code=404, detail="iteration not found")
    try:
        relative = Path(artifact_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError
        docs_root = pipeline.docs_root(iteration_id).resolve()
        path = (docs_root / relative).resolve()
        path.relative_to(docs_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="artifact path is outside iteration docs")
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    if path.is_dir():
        files = [
            item.relative_to(docs_root).as_posix()
            for item in sorted(path.rglob("*"))
            if item.is_file()
        ]
        return {"path": relative.as_posix(), "files": files}
    return FileResponse(path)


@app.get("/api/iterations/{iteration_id}/workflow-snapshot", response_model=WorkflowSnapshot)
def get_workflow_snapshot(iteration_id: str) -> WorkflowSnapshot:
    try:
        return WorkflowSnapshot(**pipeline.workflow_snapshot(iteration_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="iteration not found") from None


@app.get("/api/iterations/{iteration_id}/log-summary", response_model=LogSummaryResponse)
def get_log_summary(iteration_id: str) -> LogSummaryResponse:
    try:
        return LogSummaryResponse(**pipeline.log_summary(iteration_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="iteration not found") from None


@app.post("/api/iterations/{iteration_id}/log-summary/generate", response_model=LogSummaryResponse)
def generate_log_summary(iteration_id: str) -> LogSummaryResponse:
    try:
        pipeline.log_summary(iteration_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="iteration not found") from None
    pipeline._add_event(iteration_id, event_type="log_summary.queued", payload={})
    job_queue.enqueue_log_summary(iteration_id)
    return LogSummaryResponse(**pipeline.log_summary(iteration_id))


@app.get("/api/iterations/{iteration_id}/runs/{run_id}/logs")
def get_run_logs(
    iteration_id: str,
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    try:
        page = pipeline.run_logs_page(iteration_id, run_id, offset=offset, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    legacy_stdout = "\n".join(item.get("text", "") for item in page["items"] if item.get("stream") == "stdout")
    legacy_stderr = "\n".join(item.get("text", "") for item in page["items"] if item.get("stream") == "stderr")
    return {**page, "stdout": legacy_stdout, "stderr": legacy_stderr}


@app.get("/api/iterations/{iteration_id}/runs/{run_id}/prompt-bundle")
def get_run_prompt_bundle(iteration_id: str, run_id: str) -> dict[str, object]:
    try:
        return pipeline.run_prompt_bundle(iteration_id, run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="prompt bundle not found") from None


@app.get("/api/iterations/{iteration_id}/runs/{run_id}/worker-ref")
def get_run_worker_ref(iteration_id: str, run_id: str) -> dict[str, object]:
    try:
        return pipeline.run_worker_ref(iteration_id, run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="worker ref not found") from None


@app.get("/api/iterations/{iteration_id}/runs/{run_id}/context-package", response_model=ContextPackage)
def get_run_context_package(iteration_id: str, run_id: str) -> ContextPackage:
    try:
        return ContextPackage(**pipeline.run_context_package(iteration_id, run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="context package not found") from None


@app.websocket("/ws/iterations/{iteration_id}")
async def ws_iteration(websocket: WebSocket, iteration_id: str) -> None:
    await websocket.accept()
    row = db.get_iteration_row(iteration_id)
    if row is None:
        await websocket.close(code=4404)
        return
    queue = broker.subscribe(iteration_id)
    send_lock = asyncio.Lock()

    async def _safe_send_json(payload: dict) -> bool:
        try:
            async with send_lock:
                await websocket.send_json(payload)
            return True
        except (RuntimeError, WebSocketDisconnect):
            return False

    async def _receive() -> None:
        try:
            while True:
                data = await websocket.receive_json()
                if isinstance(data, dict) and data.get("type") == "ping":
                    sent = await _safe_send_json({"type": "pong"})
                    if not sent:
                        return
        except (RuntimeError, WebSocketDisconnect):
            return

    receive_task = asyncio.create_task(_receive())
    try:
        sent = await _safe_send_json({"type": "snapshot", "snapshot": pipeline.dashboard_snapshot(iteration_id)})
        if not sent:
            return
        while not receive_task.done():
            try:
                envelope = queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.1)
                continue
            payload = {"type": envelope.type}
            if envelope.event is not None:
                payload["event"] = envelope.event
            if envelope.snapshot is not None:
                payload["snapshot"] = envelope.snapshot
            sent = await _safe_send_json(payload)
            if not sent:
                return
    except asyncio.CancelledError:
        raise
    except (RuntimeError, WebSocketDisconnect):
        return
    finally:
        receive_task.cancel()
        with suppress(asyncio.CancelledError):
            await receive_task
        broker.unsubscribe(iteration_id, queue)


def json_loads(value: str | None) -> dict[str, int]:
    if not value:
        return {}
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def project_counts(project_id: str) -> dict[str, int]:
    bucket = {"total": 0, "active": 0, "delivered": 0}
    for iteration in db.list_iterations(project_id=project_id):
        bucket["total"] += 1
        if iteration["status"] == "delivered":
            bucket["delivered"] += 1
        elif iteration["status"] not in {"blocked", "blocked_user", "failed", "stopped"}:
            bucket["active"] += 1
    return bucket


def _cli_bindings_from_row(row) -> CliBindings | None:
    if "cli_bindings" not in row.keys() or not row["cli_bindings"]:
        return None
    parsed = parse_cli_bindings(row["cli_bindings"])
    if not parsed:
        return None
    defaults = CliBindings().model_dump()
    defaults.update(parsed)
    return CliBindings(**{key: CliProviderName(defaults[key]) for key in defaults})


def project_summary(row, counts: dict[str, int] | None = None) -> ProjectSummary:
    bucket = counts or {"total": 0, "active": 0, "delivered": 0}
    return ProjectSummary(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"] if "root_path" in row.keys() else None,
        description=row["description"],
        default_mode=row["default_mode"],
        default_test_command=row["default_test_command"],
        default_build_command=row["default_build_command"] if "default_build_command" in row.keys() else None,
        cli_bindings=_cli_bindings_from_row(row),
        coder_model=row["coder_model"],
        max_coder_tester_retries=row["max_coder_tester_retries"],
        max_clarifications=row["max_clarifications"],
        max_verify_rejects=row["max_verify_rejects"],
        max_tester_self_retries=row["max_tester_self_retries"] if "max_tester_self_retries" in row.keys() else 3,
        max_discovery_rounds=row["max_discovery_rounds"] if "max_discovery_rounds" in row.keys() else 8,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        iteration_count=bucket["total"],
        active_count=bucket["active"],
        delivered_count=bucket["delivered"],
    )


def iteration_summary(row) -> IterationSummary:
    return IterationSummary(
        id=row["id"],
        project_id=row["project_id"],
        epic_id=row["epic_id"],
        project_name=row["project_name"],
        goal=row["goal"],
        mode=row["mode"],
        status=row["status"],
        current_node=row["current_node"],
        stopped_at_node=row["stopped_at_node"] if "stopped_at_node" in row.keys() else None,
        retry_counts=json_loads(row["retry_counts"]),
        last_error=pipeline._truncate_public_text(row["last_error"], pipeline._PUBLIC_EVENT_TEXT_MAX_CHARS) if row["last_error"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def epic_counts(epic_id: str) -> dict[str, int]:
    bucket = {"total": 0, "active": 0, "blocked": 0, "delivered": 0}
    for iteration in db.list_iterations(epic_id=epic_id):
        bucket["total"] += 1
        if iteration["status"] == "delivered":
            bucket["delivered"] += 1
        elif iteration["status"] in {"blocked", "blocked_user", "failed", "stopped"}:
            bucket["blocked"] += 1
        else:
            bucket["active"] += 1
    return bucket


def epic_summary(row) -> EpicSummary:
    db.update_epic_status(row["id"])
    refreshed = db.get_epic_row(row["id"]) or row
    counts = epic_counts(row["id"])
    return EpicSummary(
        id=refreshed["id"],
        project_id=refreshed["project_id"],
        title=refreshed["title"],
        description=refreshed["description"],
        acceptance_criteria=refreshed["acceptance_criteria"],
        status=refreshed["status"],
        iteration_count=counts["total"],
        active_count=counts["active"],
        blocked_count=counts["blocked"],
        delivered_count=counts["delivered"],
        created_at=refreshed["created_at"],
        updated_at=refreshed["updated_at"],
    )


def epic_detail(row) -> EpicDetail:
    summary = epic_summary(row)
    iterations = [iteration_summary(item) for item in db.list_iterations(epic_id=row["id"])]
    return EpicDetail(**summary.model_dump(), iterations=iterations)


def refresh_iteration_epic(iteration_id: str) -> None:
    row = db.get_iteration_row(iteration_id)
    if row is not None and row["epic_id"]:
        db.update_epic_status(row["epic_id"])
