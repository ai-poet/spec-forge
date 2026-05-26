from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Mode(str, Enum):
    dry_run = "dry-run"
    real_cli = "real-cli"


class IterationStatus(str, Enum):
    created = "created"
    planning = "planning"
    awaiting_design_approval = "awaiting_design_approval"
    coding = "coding"
    testing = "testing"
    awaiting_verify_approval = "awaiting_verify_approval"
    delivered = "delivered"
    blocked = "blocked"
    failed = "failed"
    stopped = "stopped"


class NodeName(str, Enum):
    planner = "planner"
    coder = "coder"
    tester = "tester"


class CreateIterationRequest(BaseModel):
    project_name: str = Field(default="", min_length=0)
    project_id: Optional[str] = None
    goal: str = Field(min_length=1)
    mode: Mode = Mode.dry_run
    test_command: Optional[str] = None


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    iteration_count: int = 0
    active_count: int = 0
    delivered_count: int = 0


class IterationSummary(BaseModel):
    id: str
    project_id: Optional[str] = None
    project_name: str
    goal: str
    mode: Mode
    status: IterationStatus
    current_node: Optional[NodeName] = None
    created_at: datetime
    updated_at: datetime


class DocumentRecord(BaseModel):
    name: str
    path: str
    checksum: str
    created_at: datetime
    updated_at: datetime


class NodeRunRecord(BaseModel):
    id: str
    iteration_id: str
    node: NodeName
    status: str
    command: str
    stdout: str
    stderr: str
    exit_code: Optional[int]
    started_at: datetime
    finished_at: Optional[datetime]


class EventRecord(BaseModel):
    id: str
    iteration_id: str
    type: str
    payload: dict[str, Any]
    created_at: datetime


class IterationDetail(IterationSummary):
    test_command: Optional[str] = None
    graph_next: list[str] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    runs: list[NodeRunRecord] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RetryRequest(BaseModel):
    note: Optional[str] = None
