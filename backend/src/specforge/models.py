from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .contracts import UITestResult


class Mode(str, Enum):
    dry_run = "dry-run"
    real_cli = "real-cli"


class IterationStatus(str, Enum):
    created = "created"
    queued = "queued"
    planning = "planning"
    awaiting_design_approval = "awaiting_design_approval"
    coding = "coding"
    retrying = "retrying"
    testing = "testing"
    awaiting_verify_approval = "awaiting_verify_approval"
    delivered = "delivered"
    blocked = "blocked"
    blocked_user = "blocked_user"
    failed = "failed"
    stopped = "stopped"


class NodeName(str, Enum):
    planner = "planner"
    coder = "coder"
    coder_retry = "coder_retry"
    integrity_check = "integrity_check"
    tester = "tester"
    planner_clarification = "planner_clarification"
    planner_verify = "planner_verify"


class CreateIterationRequest(BaseModel):
    project_name: str = Field(default="", min_length=0)
    project_id: Optional[str] = None
    epic_id: Optional[str] = None
    goal: str = Field(min_length=1)
    mode: Optional[Mode] = None
    test_command: Optional[str] = None


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    create_if_missing: bool = False
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    default_mode: Mode = Mode.dry_run
    default_test_command: Optional[str] = None
    max_coder_tester_retries: int = Field(default=5, ge=0, le=20)
    max_clarifications: int = Field(default=3, ge=0, le=20)
    max_verify_rejects: int = Field(default=2, ge=0, le=20)


class ValidateProjectPathRequest(BaseModel):
    root_path: str = Field(min_length=1)
    create_if_missing: bool = False


class BrowseDirectoryEntry(BaseModel):
    name: str
    path: str


class BrowseQuickRoot(BaseModel):
    label: str
    path: str


class BrowseDirectoryResponse(BaseModel):
    path: str
    parent: Optional[str] = None
    entries: list[BrowseDirectoryEntry]
    quick_roots: list[BrowseQuickRoot] = Field(default_factory=list)


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    default_mode: Optional[Mode] = None
    default_test_command: Optional[str] = None
    max_coder_tester_retries: Optional[int] = Field(default=None, ge=0, le=20)
    max_clarifications: Optional[int] = Field(default=None, ge=0, le=20)
    max_verify_rejects: Optional[int] = Field(default=None, ge=0, le=20)


class EpicStatus(str, Enum):
    draft = "draft"
    active = "active"
    blocked = "blocked"
    delivered = "delivered"


class CreateEpicRequest(BaseModel):
    project_id: str
    title: str = Field(min_length=1)
    description: str = ""
    acceptance_criteria: str = ""


class UpdateEpicRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    root_path: Optional[str] = None
    description: Optional[str] = None
    default_mode: Mode = Mode.dry_run
    default_test_command: Optional[str] = None
    planner_model: Optional[str] = None
    coder_model: Optional[str] = None
    tester_model: Optional[str] = None
    max_coder_tester_retries: int = 5
    max_clarifications: int = 3
    max_verify_rejects: int = 2
    created_at: datetime
    updated_at: datetime
    iteration_count: int = 0
    active_count: int = 0
    delivered_count: int = 0


class IterationSummary(BaseModel):
    id: str
    project_id: Optional[str] = None
    epic_id: Optional[str] = None
    project_name: str
    goal: str
    mode: Mode
    status: IterationStatus
    current_node: Optional[NodeName] = None
    retry_counts: dict[str, int] = Field(default_factory=dict)
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EpicSummary(BaseModel):
    id: str
    project_id: str
    title: str
    description: str = ""
    acceptance_criteria: str = ""
    status: EpicStatus = EpicStatus.draft
    iteration_count: int = 0
    active_count: int = 0
    blocked_count: int = 0
    delivered_count: int = 0
    created_at: datetime
    updated_at: datetime


class EpicDetail(EpicSummary):
    iterations: list[IterationSummary] = Field(default_factory=list)


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
    ui_results: list[UITestResult] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RetryRequest(BaseModel):
    note: Optional[str] = None
