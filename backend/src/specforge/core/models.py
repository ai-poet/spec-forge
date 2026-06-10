from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .contracts import UITestResult


class Mode(str, Enum):
    dry_run = "dry-run"
    real_cli = "real-cli"


class CliProviderName(str, Enum):
    claude = "claude"
    codex = "codex"


class CliBindings(BaseModel):
    prd_planner: CliProviderName = CliProviderName.claude
    test_planner: CliProviderName = CliProviderName.claude
    planner_discovery: CliProviderName = CliProviderName.claude
    planner_clarification: CliProviderName = CliProviderName.claude
    coder: CliProviderName = CliProviderName.claude
    code_tester: CliProviderName = CliProviderName.claude
    ui_tester: CliProviderName = CliProviderName.claude
    log_summarizer: CliProviderName = CliProviderName.claude


class IterationStatus(str, Enum):
    created = "created"
    queued = "queued"
    planning = "planning"
    awaiting_requirements_input = "awaiting_requirements_input"
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
    prd_planner = "prd_planner"
    test_planner = "test_planner"
    planner_discovery = "planner_discovery"
    coder = "coder"
    coder_retry = "coder_retry"
    integrity_check = "integrity_check"
    code_tester = "code_tester"
    ui_tester = "ui_tester"
    log_summarizer = "log_summarizer"
    planner_clarification = "planner_clarification"
    planner_verify = "planner_verify"


class CreateIterationRequest(BaseModel):
    project_name: str = Field(default="", min_length=0)
    project_id: Optional[str] = None
    epic_id: Optional[str] = None
    goal: str = Field(min_length=1)
    mode: Optional[Mode] = None
    test_command: Optional[str] = None
    build_command: Optional[str] = None


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    create_if_missing: bool = False
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    default_mode: Mode = Mode.real_cli
    default_test_command: Optional[str] = None
    default_build_command: Optional[str] = None
    max_coder_tester_retries: int = Field(default=5, ge=0, le=20)
    max_clarifications: int = Field(default=3, ge=0, le=20)
    max_verify_rejects: int = Field(default=2, ge=0, le=20)
    max_tester_self_retries: int = Field(default=3, ge=0, le=20)
    max_discovery_rounds: int = Field(default=8, ge=0, le=30)


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


class PickFolderResponse(BaseModel):
    cancelled: bool
    path: str = ""


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    root_path: Optional[str] = Field(default=None, min_length=1)
    create_if_missing: Optional[bool] = False
    default_mode: Optional[Mode] = None
    default_test_command: Optional[str] = None
    default_build_command: Optional[str] = None
    cli_bindings: Optional[CliBindings] = None
    max_coder_tester_retries: Optional[int] = Field(default=None, ge=0, le=20)
    max_clarifications: Optional[int] = Field(default=None, ge=0, le=20)
    max_verify_rejects: Optional[int] = Field(default=None, ge=0, le=20)
    max_tester_self_retries: Optional[int] = Field(default=None, ge=0, le=20)
    max_discovery_rounds: Optional[int] = Field(default=None, ge=0, le=30)


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
    default_mode: Mode = Mode.real_cli
    default_test_command: Optional[str] = None
    default_build_command: Optional[str] = None
    cli_bindings: Optional[CliBindings] = None
    coder_model: Optional[str] = None
    max_coder_tester_retries: int = 5
    max_clarifications: int = 3
    max_verify_rejects: int = 2
    max_tester_self_retries: int = 3
    max_discovery_rounds: int = 8
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
    stopped_at_node: Optional[str] = None
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
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int]
    started_at: datetime
    finished_at: Optional[datetime]
    duration_ms: Optional[int] = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    logs_url: Optional[str] = None
    raw_log_url: Optional[str] = None
    provider: Optional[str] = None
    session_id: Optional[str] = None
    session_mode: Optional[str] = None
    prompt_hash: Optional[str] = None
    prompt_url: Optional[str] = None
    worker_ref_url: Optional[str] = None
    context_package_url: Optional[str] = None
    supports_continue: bool = False
    timed_out: bool = False


class RunLogLine(BaseModel):
    stream: str
    line: int
    text: str
    node: Optional[str] = None
    created_at: Optional[str] = None


class RunLogPage(BaseModel):
    items: list[RunLogLine]
    offset: int = 0
    limit: int = 200
    total: int = 0
    has_more: bool = False


class LogSummaryStage(BaseModel):
    stage: str
    status: str
    description: str = ""
    run_ids: list[str] = Field(default_factory=list)


class LogSummaryAcceptancePoint(BaseModel):
    point: str
    status: str
    evidence: str = ""


class LogSummaryResponse(BaseModel):
    generated: bool = False
    generating: bool = False
    generated_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None
    stages: list[LogSummaryStage] = Field(default_factory=list)
    final_summary: str = ""
    acceptance_points: list[LogSummaryAcceptancePoint] = Field(default_factory=list)
    risks_or_followups: list[str] = Field(default_factory=list)


class EventRecord(BaseModel):
    id: str
    iteration_id: str
    type: str
    payload: dict[str, Any]
    created_at: datetime


class LiveCliOutput(BaseModel):
    node: str
    stdout: str = ""
    stderr: str = ""


class PendingDiscovery(BaseModel):
    round: int
    question: str
    options: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class DiscoveryHistoryEntry(BaseModel):
    round: int
    question: str
    answer: str


class IterationDetail(IterationSummary):
    test_command: Optional[str] = None
    graph_next: list[str] = Field(default_factory=list)
    pending_discovery: Optional[PendingDiscovery] = None
    discovery_history: list[DiscoveryHistoryEntry] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    runs: list[NodeRunRecord] = Field(default_factory=list)
    ui_results: list[UITestResult] = Field(default_factory=list)
    live_cli: Optional[LiveCliOutput] = None


class ApproveRequest(BaseModel):
    note: Optional[str] = None


class AnswerRequirementsRequest(BaseModel):
    answer: str = Field(min_length=1)


class RetryRequest(BaseModel):
    note: Optional[str] = None


class ManualSkipRequest(BaseModel):
    node: Optional[str] = None
    note: Optional[str] = None


class ProjectProfileRequest(BaseModel):
    name: str = Field(min_length=1)
    summary: str = ""
    stage: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ProjectProfile(BaseModel):
    id: str
    name: str
    summary: str = ""
    stage: str
    content: str
    created_at: str
    updated_at: str
    path: str


class ProfileBindingsRequest(BaseModel):
    bindings: dict[str, Optional[str]] = Field(default_factory=dict)


class ProfileBindingsResponse(BaseModel):
    bindings: dict[str, Optional[str]] = Field(default_factory=dict)


class WorkflowSnapshot(BaseModel):
    version: str
    kind: str
    iteration_id: Optional[str] = None
    project_id: Optional[str] = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    retry_budget: dict[str, int] = Field(default_factory=dict)
    profile_bindings: dict[str, Optional[str]] = Field(default_factory=dict)


class ContextPackage(BaseModel):
    version: str
    run_id: str
    node: str
    profile: Optional[dict[str, Any]] = None
    hot_docs: list[dict[str, Any]] = Field(default_factory=list)
    cold_manifest: list[dict[str, Any]] = Field(default_factory=list)
    runtime_notes: list[dict[str, Any]] = Field(default_factory=list)
    previous_feedback: list[dict[str, Any]] = Field(default_factory=list)
    iteration_root: str
    docs_root: str
