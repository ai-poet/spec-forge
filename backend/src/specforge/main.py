from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .cli_runner import DryRunRunner, RealCLIRunner
from .config import settings
from .db import Database
from .models import (
    ApproveRequest,
    CreateIterationRequest,
    CreateProjectRequest,
    IterationDetail,
    IterationSummary,
    ProjectSummary,
    RetryRequest,
)
from .pipeline import LangGraphPipeline


db = Database(settings.db_path)
db.init()


def make_runner():
    if settings.mode == "real-cli":
        return RealCLIRunner()
    return DryRunRunner()


pipeline = LangGraphPipeline(db=db, runner=make_runner())

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
        elif iteration["status"] not in {"blocked", "failed", "stopped"}:
            bucket["active"] += 1
    items = []
    for row in db.list_projects():
        bucket = counts.get(row["id"], {"total": 0, "active": 0, "delivered": 0})
        items.append(
            ProjectSummary(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                iteration_count=bucket["total"],
                active_count=bucket["active"],
                delivered_count=bucket["delivered"],
            )
        )
    return items


@app.post("/api/projects", response_model=ProjectSummary)
def create_project(payload: CreateProjectRequest) -> ProjectSummary:
    project_id = db.create_project(name=payload.name, description=payload.description)
    row = db.get_project_row(project_id)
    assert row is not None
    return ProjectSummary(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


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
        mode=payload.mode.value,
        test_command=payload.test_command,
    )
    pipeline.start(iteration_id)
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
    try:
        pipeline.approve_design(iteration_id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return get_iteration(iteration_id)


@app.post("/api/iterations/{iteration_id}/approve-verify", response_model=IterationSummary)
def approve_verify(iteration_id: str, payload: ApproveRequest) -> IterationSummary:
    try:
        pipeline.approve_verify(iteration_id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    try:
        import asyncio

        while True:
            await websocket.send_json(pipeline.dashboard_snapshot(iteration_id))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
