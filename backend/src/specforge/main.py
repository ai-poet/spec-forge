from __future__ import annotations

from typing import Optional

import asyncio

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .cli_runner import DryRunRunner, RealCLIRunner
from .config import settings
from .db import Database
from .events import EventBroker, EventEnvelope
from .job_queue import PipelineJobQueue
from .models import (
    ApproveRequest,
    CreateIterationRequest,
    CreateProjectRequest,
    IterationDetail,
    IterationSummary,
    ProjectSummary,
    RetryRequest,
    UpdateProjectRequest,
)
from .pipeline import LangGraphPipeline


db = Database(settings.db_path)
db.init()


def make_runner():
    if settings.mode == "real-cli":
        return RealCLIRunner()
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.post("/api/projects", response_model=ProjectSummary)
def create_project(payload: CreateProjectRequest) -> ProjectSummary:
    project_id = db.create_project(
        name=payload.name,
        description=payload.description,
        default_mode=payload.default_mode.value,
        default_test_command=payload.default_test_command,
        planner_model=payload.planner_model,
        coder_model=payload.coder_model,
        tester_model=payload.tester_model,
        max_coder_tester_retries=payload.max_coder_tester_retries,
        max_clarifications=payload.max_clarifications,
        max_verify_rejects=payload.max_verify_rejects,
    )
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
    if "default_mode" in data and data["default_mode"] is not None:
        data["default_mode"] = data["default_mode"].value
    db.update_project(project_id, **data)
    updated = db.get_project_row(project_id)
    assert updated is not None
    return project_summary(updated, project_counts(project_id))


@app.get("/api/iterations", response_model=list[IterationSummary])
def list_iterations(project_id: Optional[str] = Query(default=None)) -> list[IterationSummary]:
    items = []
    for row in db.list_iterations(project_id=project_id):
        items.append(
            IterationSummary(
                id=row["id"],
                project_id=row["project_id"],
                project_name=row["project_name"],
                goal=row["goal"],
                mode=row["mode"],
                status=row["status"],
                current_node=row["current_node"],
                retry_counts=json_loads(row["retry_counts"]),
                last_error=row["last_error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    return items


@app.post("/api/iterations", response_model=IterationSummary)
def create_iteration(payload: CreateIterationRequest) -> IterationSummary:
    project_name = payload.project_name
    if payload.project_id:
        project = db.get_project_row(payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        project_name = project["name"]
    if not project_name:
        raise HTTPException(status_code=422, detail="project_name or project_id is required")
    iteration_id = db.create_iteration(
        project_name=project_name,
        project_id=payload.project_id,
        goal=payload.goal,
        mode=payload.mode.value if payload.mode else None,
        test_command=payload.test_command,
    )
    db.update_iteration(iteration_id, status="queued", current_node=None)
    db.add_event(iteration_id, event_type="iteration.queued", payload={"job": "start"})
    broker.publish(iteration_id, EventEnvelope(type="snapshot", snapshot=pipeline.dashboard_snapshot(iteration_id)))
    job_queue.enqueue_start(iteration_id)
    row = db.get_iteration_row(iteration_id)
    assert row is not None
    return IterationSummary(
        id=row["id"],
        project_id=row["project_id"],
        project_name=row["project_name"],
        goal=row["goal"],
        mode=row["mode"],
        status=row["status"],
        current_node=row["current_node"],
        retry_counts=json_loads(row["retry_counts"]),
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.get("/api/iterations/{iteration_id}", response_model=IterationDetail)
def get_iteration(iteration_id: str) -> IterationDetail:
    row = db.get_iteration_row(iteration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="iteration not found")
    snapshot = pipeline.dashboard_snapshot(iteration_id)
    return IterationDetail(
        id=snapshot["id"],
        project_id=snapshot["project_id"],
        project_name=snapshot["project_name"],
        goal=snapshot["goal"],
        mode=snapshot["mode"],
        status=snapshot["status"],
        current_node=snapshot["current_node"],
        retry_counts=snapshot["retry_counts"],
        last_error=snapshot["last_error"],
        created_at=snapshot["created_at"],
        updated_at=snapshot["updated_at"],
        test_command=snapshot["test_command"],
        graph_next=snapshot["graph_next"],
        documents=snapshot["documents"],
        events=snapshot["events"],
        runs=snapshot["runs"],
    )


@app.post("/api/iterations/{iteration_id}/approve-design", response_model=IterationSummary)
def approve_design(iteration_id: str, payload: ApproveRequest) -> IterationSummary:
    if not pipeline.can_resume(iteration_id, "design_approval"):
        raise HTTPException(status_code=409, detail="iteration is not awaiting design_approval")
    db.add_event(iteration_id, event_type="resume.queued", payload={"checkpoint": "design_approval"})
    job_queue.enqueue_resume(iteration_id, "design_approval", payload.note)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/approve-verify", response_model=IterationSummary)
def approve_verify(iteration_id: str, payload: ApproveRequest) -> IterationSummary:
    if not pipeline.can_resume(iteration_id, "verify_approval"):
        raise HTTPException(status_code=409, detail="iteration is not awaiting verify_approval")
    db.add_event(iteration_id, event_type="resume.queued", payload={"checkpoint": "verify_approval"})
    job_queue.enqueue_resume(iteration_id, "verify_approval", payload.note)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/retry", response_model=IterationSummary)
def retry_iteration(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    pipeline.retry(iteration_id, note=payload.note)
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/stop", response_model=IterationSummary)
def stop_iteration(iteration_id: str, payload: RetryRequest) -> IterationSummary:
    pipeline.stop_iteration(iteration_id, reason=payload.note or "stopped")
    return get_iteration(iteration_id)


@app.get("/api/iterations/{iteration_id}/documents/{name}")
def get_document(iteration_id: str, name: str) -> dict[str, str]:
    docs = db.list_documents(iteration_id)
    for doc in docs:
        if doc["name"] == name:
            from pathlib import Path

            path = Path(doc["path"])
            return {"name": name, "content": path.read_text(encoding="utf-8"), "checksum": doc["checksum"]}
    raise HTTPException(status_code=404, detail="document not found")


@app.get("/api/iterations/{iteration_id}/runs/{run_id}/logs")
def get_run_logs(iteration_id: str, run_id: str) -> dict[str, str]:
    for run in db.list_runs(iteration_id):
        if run["id"] == run_id:
            return {"stdout": run["stdout"], "stderr": run["stderr"]}
    raise HTTPException(status_code=404, detail="run not found")


@app.websocket("/ws/iterations/{iteration_id}")
async def ws_iteration(websocket: WebSocket, iteration_id: str) -> None:
    await websocket.accept()
    row = db.get_iteration_row(iteration_id)
    if row is None:
        await websocket.close(code=4404)
        return
    queue = broker.subscribe(iteration_id)
    try:
        await websocket.send_json({"type": "snapshot", "snapshot": pipeline.dashboard_snapshot(iteration_id)})
        while True:
            envelope = await asyncio.to_thread(queue.get)
            await websocket.send_json({"type": envelope.type, "event": envelope.event, "snapshot": envelope.snapshot})
    except WebSocketDisconnect:
        return
    finally:
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


def project_summary(row, counts: dict[str, int] | None = None) -> ProjectSummary:
    bucket = counts or {"total": 0, "active": 0, "delivered": 0}
    return ProjectSummary(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        default_mode=row["default_mode"],
        default_test_command=row["default_test_command"],
        planner_model=row["planner_model"],
        coder_model=row["coder_model"],
        tester_model=row["tester_model"],
        max_coder_tester_retries=row["max_coder_tester_retries"],
        max_clarifications=row["max_clarifications"],
        max_verify_rejects=row["max_verify_rejects"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        iteration_count=bucket["total"],
        active_count=bucket["active"],
        delivered_count=bucket["delivered"],
    )
