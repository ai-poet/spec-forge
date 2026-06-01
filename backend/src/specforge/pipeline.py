from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from typing_extensions import TypedDict

from .cli_commands import (
    CliStage,
    build_coder_command,
    build_planner_clarification_command,
    build_planner_command,
    build_planner_discovery_command,
    build_tester_command,
    parse_cli_bindings,
    resolve_cli_provider,
)
from .cli_runner import BaseRunner, CLIResult, DryRunRunner, RealCLIRunner
from .cli_event_presenter import CliDisplayEvent, CliEventPresenter
from .config import settings
from .contracts import (
    ArtifactFile,
    CoderArtifact,
    ContextManifestEntry,
    Defect,
    PlannerArtifact,
    PlannerClarificationArtifact,
    PlannerDiscoveryArtifact,
    TesterArtifact,
    UIDriverRunResult,
    UITestResult,
    UITestSpec,
    UI_TEST_ACTIONS,
    merge_cli_artifact_output,
    parse_json_artifact,
    ui_spec_error_type,
    validate_ui_spec_content,
)
from .db import Database, iso, utcnow
from .docs_io import IterationDocs, checksum, compare_test_integrity, safe_relative_path, test_integrity_manifest
from .docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root
from .events import EventBroker, EventEnvelope
from .artifact_gate import read_convention_excerpt, read_framework_conventions, read_spec_index, run_project_commands
from .context_manifest import (
    FOR_CODER,
    FOR_TESTER,
    RUNTIME_NOTES,
    append_runtime_note,
    format_manifest_for_prompt,
    format_runtime_notes_section,
    resolve_coder_manifest,
    resolve_tester_manifest,
    write_jsonl,
)
from .prompt_loader import compose_stage_prompt
from .write_zones import enrich_defects, retry_target, summarize_failure_notes
from .models import IterationStatus, Mode, NodeName
from .ui_driver import UIDriverRunner
from .cua_bootstrap import CUA_INSTALL_HINT
from .ui_runtime import UI_DRIVER_INSTALL_HINT


def _last_str(left: str | None, right: str | None) -> str | None:
    if right == "":
        return None
    return right if right is not None else left


def _merge_counts(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


class PipelineState(TypedDict, total=False):
    iteration_id: str
    project_id: Optional[str]
    project_name: str
    goal: str
    epic_title: Optional[str]
    epic_description: Optional[str]
    epic_acceptance_criteria: Optional[str]
    mode: str
    status: Annotated[str, _last_str]
    route: Annotated[str | None, _last_str]
    current_node: Optional[str]
    design_approval: Optional[str]
    verify_approval: Optional[str]
    blocked_reason: Optional[str]
    failure_notes: Optional[str]
    retry_target: Optional[str]
    clarification_request: Optional[str]
    retry_counts: Annotated[dict[str, int], _merge_counts]
    max_coder_tester_retries: int
    max_tester_self_retries: int
    max_clarifications: int
    max_verify_rejects: int
    max_discovery_rounds: int
    requirements_brief: Annotated[str, _last_str]
    discovery_qa: list[dict[str, Any]]
    pending_discovery_question: Optional[str]
    pending_discovery_options: list[str]
    pending_discovery_assumptions: list[str]
    planner_run_id: Optional[str]
    coder_run_id: Optional[str]
    tester_run_id: Optional[str]


class LangGraphPipeline:
    def __init__(self, db: Database, runner: BaseRunner, broker: Optional[EventBroker] = None) -> None:
        self.db = db
        self.runner = runner
        self.broker = broker or EventBroker()
        self.dry_runner = DryRunRunner()
        self.real_runner = RealCLIRunner()
        self.cli_presenter = CliEventPresenter()
        self.ui_driver = UIDriverRunner()
        settings.langgraph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpointer_context = SqliteSaver.from_conn_string(str(settings.langgraph_db_path))
        self._checkpointer = self._checkpointer_context.__enter__()
        self.graph = self._build_graph().compile(checkpointer=self._checkpointer)
        self._live_cli_lock = Lock()
        self._live_cli: dict[str, dict[str, str]] = {}
        self._live_cli_last_publish: dict[str, float] = {}
        self._live_cli_chunk_last_publish: dict[str, float] = {}
        self._aborted_iterations: set[str] = set()
        self._invoking: set[str] = set()

    def project_repo_root(self, iteration_id: str) -> Path:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        if project is not None and project["root_path"]:
            return Path(project["root_path"])
        return settings.projects_dir / row["project_name"]

    def project_root(self, iteration_id: str) -> Path:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        if project is not None and project["root_path"]:
            return Path(project["root_path"]) / ".specforge" / "iterations" / iteration_id
        return settings.projects_dir / iteration_id

    def docs_root(self, iteration_id: str) -> Path:
        row = self._require_iteration(iteration_id)
        docs_slug = row["docs_slug"] if "docs_slug" in row.keys() and row["docs_slug"] else iteration_id
        return iteration_docs_root(self.project_repo_root(iteration_id), docs_slug)

    def _prepare_iteration_docs(self, iteration_id: str) -> Path:
        row = self._require_iteration(iteration_id)
        repo_root = self.project_repo_root(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        project_name = project["name"] if project is not None else row["project_name"]
        description = project["description"] if project is not None else None
        docs_slug = row["docs_slug"] if "docs_slug" in row.keys() and row["docs_slug"] else iteration_id
        ensure_project_docs(repo_root, project_name=project_name, description=description)
        return ensure_iteration_docs(repo_root, docs_slug)

    def start(self, iteration_id: str) -> None:
        self._begin_invoke(iteration_id)
        try:
            state = self._build_state(iteration_id)
            self.graph.invoke(state, config=self._config(iteration_id))
        finally:
            self._end_invoke(iteration_id)
        self._publish_snapshot(iteration_id)

    def _build_state(self, iteration_id: str) -> PipelineState:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        epic = self.db.get_epic_row(row["epic_id"]) if row["epic_id"] else None
        retry_counts = self._json(row["retry_counts"], {})
        return {
            "iteration_id": iteration_id,
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "goal": row["goal"],
            "epic_title": epic["title"] if epic else None,
            "epic_description": epic["description"] if epic else None,
            "epic_acceptance_criteria": epic["acceptance_criteria"] if epic else None,
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
            "retry_counts": retry_counts,
            "max_coder_tester_retries": int(project["max_coder_tester_retries"]) if project else 5,
            "max_tester_self_retries": int(project["max_tester_self_retries"]) if project and "max_tester_self_retries" in project.keys() else 3,
            "max_clarifications": int(project["max_clarifications"]) if project else 3,
            "max_verify_rejects": int(project["max_verify_rejects"]) if project else 2,
            "max_discovery_rounds": int(project["max_discovery_rounds"]) if project and "max_discovery_rounds" in project.keys() else 8,
            "discovery_qa": [],
            "requirements_brief": "",
        }

    def answer_requirements(self, iteration_id: str, answer: str) -> None:
        self.resume(iteration_id, "requirements_input", answer)

    def skip_discovery(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "requirements_input", f"SKIP:{note or 'proceed with documented assumptions'}")

    def approve_design(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "design_approval", note or "approved")

    def approve_verify(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "verify_approval", note or "approved")

    def resume(self, iteration_id: str, expected_checkpoint: str, note: str) -> None:
        state = self.graph.get_state(self._config(iteration_id))
        if expected_checkpoint not in set(state.next):
            raise ValueError(f"iteration is not awaiting {expected_checkpoint}")
        self._begin_invoke(iteration_id)
        try:
            self.graph.invoke(Command(resume=note), config=self._config(iteration_id))
        finally:
            self._end_invoke(iteration_id)
        self._publish_snapshot(iteration_id)

    def can_resume(self, iteration_id: str, expected_checkpoint: str) -> bool:
        state = self.graph.get_state(self._config(iteration_id))
        return expected_checkpoint in set(state.next)

    def cancel_cli(self, iteration_id: str) -> None:
        self._aborted_iterations.add(iteration_id)
        self.real_runner.cancel(iteration_id)
        self._clear_live_cli(iteration_id)

    def stop_iteration(self, iteration_id: str, reason: str = "stopped by user") -> None:
        row = self.db.get_iteration_row(iteration_id)
        if row is None:
            return
        stopped_at_node = self._stopped_resume_node(row)
        self.cancel_cli(iteration_id)
        self._update_iteration(
            iteration_id,
            status=IterationStatus.stopped.value,
            current_node=None,
            stopped_at_node=stopped_at_node,
            last_error=reason,
        )
        self._add_event(
            iteration_id,
            event_type="iteration.stopped",
            payload={"reason": reason, "node": stopped_at_node},
        )

    def can_resume_stopped(self, iteration_id: str) -> bool:
        row = self.db.get_iteration_row(iteration_id)
        if row is None or row["status"] != IterationStatus.stopped.value:
            return False
        return self._stopped_resume_node(row) is not None

    def resume_stopped(self, iteration_id: str, note: Optional[str] = None) -> None:
        row = self._require_iteration(iteration_id)
        if row["status"] != IterationStatus.stopped.value:
            raise ValueError("iteration is not stopped")
        resume_node = self._stopped_resume_node(row)
        if not resume_node:
            raise ValueError("cannot determine resume step")

        self._aborted_iterations.discard(iteration_id)
        config = self._config(iteration_id)

        if resume_node == "requirements_input" and self.can_resume(iteration_id, "requirements_input"):
            self.resume(iteration_id, "requirements_input", note or "resumed")
            return
        if resume_node == "design_approval" and self.can_resume(iteration_id, "design_approval"):
            self.approve_design(iteration_id, note=note)
            return
        if resume_node == "verify_approval" and self.can_resume(iteration_id, "verify_approval"):
            self._update_iteration(
                iteration_id,
                status=IterationStatus.awaiting_verify_approval.value,
                current_node=None,
                stopped_at_node=None,
                last_error=None,
            )
            self._add_event(
                iteration_id,
                event_type="iteration.resumed",
                payload={"node": resume_node, "note": note},
            )
            self._begin_invoke(iteration_id)
            try:
                self.graph.invoke(Command(resume=note or "resumed"), config=config)
            finally:
                self._end_invoke(iteration_id)
            self._publish_snapshot(iteration_id)
            return

        resume_status = self._status_for_node(resume_node)
        self._update_iteration(
            iteration_id,
            status=resume_status.value,
            current_node=resume_node,
            stopped_at_node=None,
            last_error=None,
        )
        self._add_event(
            iteration_id,
            event_type="iteration.resumed",
            payload={"node": resume_node, "note": note},
        )

        state = self._build_state(iteration_id)
        graph_state = self.graph.get_state(config)
        if graph_state.values:
            merged = dict(graph_state.values)
            merged.update(state)
            state = merged
        self.graph.update_state(config, state)
        self._begin_invoke(iteration_id)
        try:
            self.graph.invoke(Command(goto=resume_node), config=config)
        finally:
            self._end_invoke(iteration_id)
        self._publish_snapshot(iteration_id)

    def _stopped_resume_node(self, row: Any) -> Optional[str]:
        if "stopped_at_node" in row.keys() and row["stopped_at_node"]:
            return row["stopped_at_node"]
        if row["current_node"]:
            return row["current_node"]
        return self._infer_node_from_status(row["status"])

    def _infer_node_from_status(self, status: str) -> Optional[str]:
        return {
            "queued": NodeName.planner.value,
            "created": NodeName.planner.value,
            "planning": NodeName.planner_discovery.value,
            "awaiting_requirements_input": "requirements_input",
            "awaiting_design_approval": "design_approval",
            "coding": NodeName.coder.value,
            "retrying": NodeName.coder.value,
            "testing": NodeName.tester.value,
            "awaiting_verify_approval": "verify_approval",
        }.get(status)

    def _status_for_node(self, node: str) -> IterationStatus:
        mapping = {
            NodeName.planner_discovery.value: IterationStatus.planning,
            NodeName.planner.value: IterationStatus.planning,
            NodeName.planner_clarification.value: IterationStatus.retrying,
            "requirements_input": IterationStatus.awaiting_requirements_input,
            "design_approval": IterationStatus.awaiting_design_approval,
            NodeName.coder.value: IterationStatus.coding,
            NodeName.integrity_check.value: IterationStatus.testing,
            NodeName.tester.value: IterationStatus.testing,
            NodeName.planner_verify.value: IterationStatus.testing,
            "verify_approval": IterationStatus.awaiting_verify_approval,
        }
        return mapping.get(node, IterationStatus.queued)

    def retry(self, iteration_id: str, note: Optional[str] = None) -> None:
        row = self._require_iteration(iteration_id)
        if row["status"] == IterationStatus.awaiting_verify_approval.value:
            self.approve_verify(iteration_id, note=note)

    def fail_job(self, iteration_id: str, reason: str) -> None:
        self._block(iteration_id, "job.failed", None, reason)

    def dashboard_snapshot(self, iteration_id: str) -> dict[str, Any]:
        row = self._require_iteration(iteration_id)
        if iteration_id in self._invoking:
            graph_next: list[str] = []
        else:
            graph_state = self.graph.get_state(self._config(iteration_id))
            graph_next = list(graph_state.next)
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "epic_id": row["epic_id"],
            "project_name": row["project_name"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
            "stopped_at_node": row["stopped_at_node"] if "stopped_at_node" in row.keys() else None,
            "retry_counts": self._json(row["retry_counts"], {}),
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "test_command": row["test_command"],
            "graph_next": graph_next,
            "documents": [
                {
                    "name": doc["name"],
                    "path": doc["path"],
                    "checksum": doc["checksum"],
                    "created_at": doc["created_at"],
                    "updated_at": doc["updated_at"],
                }
                for doc in self.db.list_documents(iteration_id)
            ],
            "events": [
                {
                    "id": event["id"],
                    "iteration_id": event["iteration_id"],
                    "type": event["type"],
                    "payload": json.loads(event["payload"]),
                    "created_at": event["created_at"],
                }
                for event in self.db.list_events(iteration_id)
            ],
            "runs": [
                {
                    "id": run["id"],
                    "iteration_id": run["iteration_id"],
                    "node": run["node"],
                    "status": run["status"],
                    "command": run["command"],
                    "stdout": run["stdout"],
                    "stderr": run["stderr"],
                    "exit_code": run["exit_code"],
                    "started_at": run["started_at"],
                    "finished_at": run["finished_at"],
                }
                for run in self.db.list_runs(iteration_id)
            ],
            "ui_results": [result.model_dump() for result in self._ui_results(iteration_id)],
            "live_cli": self._live_cli_snapshot(iteration_id),
            **self._discovery_snapshot_fields(iteration_id),
        }

    def _live_cli_snapshot(self, iteration_id: str) -> Optional[dict[str, str]]:
        with self._live_cli_lock:
            live = self._live_cli.get(iteration_id)
            if not live:
                return None
            return {"node": live["node"], "stdout": live["stdout"], "stderr": live["stderr"]}

    def _reset_live_cli(self, iteration_id: str, node: str) -> None:
        with self._live_cli_lock:
            self._live_cli[iteration_id] = {"node": node, "stdout": "", "stderr": ""}
            self._live_cli_last_publish.pop(iteration_id, None)

    def _append_live_cli(self, iteration_id: str, stream: str, chunk: str) -> None:
        node = ""
        with self._live_cli_lock:
            live = self._live_cli.get(iteration_id)
            if live is None:
                return
            live[stream] += chunk
            node = live["node"]
        self._maybe_publish_cli_output(iteration_id, node, stream, chunk)

    def _clear_live_cli(self, iteration_id: str) -> None:
        with self._live_cli_lock:
            self._live_cli.pop(iteration_id, None)
            self._live_cli_last_publish.pop(iteration_id, None)
            self._live_cli_chunk_last_publish.pop(iteration_id, None)

    def _maybe_publish_cli_output(self, iteration_id: str, node: str, stream: str, chunk: str) -> None:
        now = time.monotonic()
        with self._live_cli_lock:
            last = self._live_cli_chunk_last_publish.get(iteration_id, 0.0)
            if now - last < 0.05:
                return
            self._live_cli_chunk_last_publish[iteration_id] = now
        try:
            self.broker.publish(
                iteration_id,
                EventEnvelope(
                    type="cli.output",
                    event={"type": "cli.output", "payload": {"node": node, "stream": stream, "chunk": chunk}},
                ),
            )
        except Exception:
            pass

    def _maybe_publish_live_cli(self, iteration_id: str) -> None:
        now = time.monotonic()
        with self._live_cli_lock:
            last = self._live_cli_last_publish.get(iteration_id, 0.0)
            if now - last < 0.15:
                return
            self._live_cli_last_publish[iteration_id] = now
        self._publish_snapshot(iteration_id)

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(PipelineState)
        builder.add_node("planner_discovery", self._planner_discovery_node)
        builder.add_node("requirements_input", self._requirements_input_node)
        builder.add_node("planner", self._planner_node)
        builder.add_node("design_approval", self._design_approval_node)
        builder.add_node("coder", self._coder_node)
        builder.add_node("planner_clarification", self._planner_clarification_node)
        builder.add_node("integrity_check", self._integrity_check_node)
        builder.add_node("tester", self._tester_node)
        builder.add_node("planner_verify", self._planner_verify_node)
        builder.add_node("verify_approval", self._verify_approval_node)
        builder.add_node("done", self._done_node)
        builder.add_edge(START, "planner_discovery")
        builder.add_conditional_edges(
            "planner_discovery",
            self._route_after_discovery,
            {"blocked": END, "ask": "requirements_input", "ready": "planner"},
        )
        builder.add_edge("requirements_input", "planner_discovery")
        builder.add_conditional_edges("planner", self._route_after_planner, {"blocked": END, "approval": "design_approval"})
        builder.add_conditional_edges("design_approval", self._route_after_design_approval, {"blocked": END, "coder": "coder"})
        builder.add_conditional_edges(
            "coder",
            self._route_after_coder,
            {"blocked": END, "clarification": "planner_clarification", "integrity": "integrity_check"},
        )
        builder.add_conditional_edges(
            "planner_clarification",
            self._route_after_clarification,
            {"blocked": END, "coder": "coder"},
        )
        builder.add_conditional_edges("integrity_check", self._route_after_integrity, {"blocked": END, "tester": "tester"})
        builder.add_conditional_edges(
            "tester",
            self._route_after_tester,
            {"blocked": END, "retry": "coder", "self_retry": "tester", "verify": "planner_verify"},
        )
        builder.add_conditional_edges("planner_verify", self._route_after_planner_verify, {"blocked": END, "tester": "tester", "approval": "verify_approval"})
        builder.add_edge("verify_approval", "done")
        builder.add_edge("done", END)
        return builder

    def _planner_discovery_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        goal = state["goal"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        self.project_root(iteration_id).mkdir(parents=True, exist_ok=True)
        self._prepare_iteration_docs(iteration_id)
        discovery_qa = list(state.get("discovery_qa") or [])
        row = self._require_iteration(iteration_id)
        docs_slug = row["docs_slug"] if "docs_slug" in row.keys() and row["docs_slug"] else iteration_id
        if not discovery_qa:
            append_iteration_log(
                self.project_repo_root(iteration_id),
                docs_slug=docs_slug,
                event="iteration.started",
                detail=f"Planning started for goal: {goal}",
            )
        max_rounds = state.get("max_discovery_rounds", 8)
        if len(discovery_qa) >= max_rounds:
            self._update_iteration(iteration_id, status=IterationStatus.blocked_user.value, current_node=None)
            return self._block(
                iteration_id,
                "discovery.max_retries",
                None,
                "discovery question cap reached",
                blocked_user=True,
            )

        self._update_iteration(
            iteration_id,
            status=IterationStatus.planning.value,
            current_node=NodeName.planner_discovery.value,
            last_error=None,
        )
        self._reset_live_cli(iteration_id, NodeName.planner_discovery.value)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.planner_discovery.value,
            "需求澄清已启动",
            "Planner 正在分析大需求，必要时将向您提出单个澄清问题。",
        )
        run_result = self._execute(
            state,
            self._planner_discovery_command(state),
            node=NodeName.planner_discovery.value,
        )
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.planner_discovery.value, run_result)
        if run_result.returncode:
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.planner_discovery.value,
                "需求澄清失败",
                "Planner discovery CLI 执行失败。",
                severity="error",
                run_id=run_id,
                action_hint="查看运行日志，确认 claude CLI 可用并能返回 JSON artifact。",
            )
            return self._block(iteration_id, "planner_discovery.failed", run_id, run_result.stderr)

        try:
            artifact = self._planner_discovery_artifact(state, run_result)
        except Exception as exc:
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.planner_discovery.value,
                "澄清产物无效",
                "Planner discovery 输出无法被解析为合法 artifact。",
                severity="error",
                run_id=run_id,
            )
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        brief_path = docs.write_text(
            "discovery/requirements_brief.md",
            self._discovery_brief_markdown(artifact.requirements_brief, artifact.assumptions, artifact.complexity),
        )
        self._record_document(iteration_id, "requirements_brief", brief_path)

        if artifact.status == "ready":
            self._add_event(
                iteration_id,
                event_type="discovery.ready",
                payload={"complexity": artifact.complexity, "rationale": artifact.rationale},
            )
            self._node_event(
                iteration_id,
                "node.completed",
                NodeName.planner_discovery.value,
                "需求已足够清晰",
                artifact.rationale or "Planner 判断无需进一步澄清，进入终局规划。",
                severity="success",
                run_id=run_id,
            )
            return {
                "route": "ready",
                "requirements_brief": artifact.requirements_brief,
                "status": IterationStatus.planning.value,
                "current_node": None,
            }

        question = (artifact.question or "").strip()
        if not question:
            return self._block(iteration_id, "discovery.missing_question", run_id, "ask status requires question")

        round_num = len(discovery_qa) + 1
        question_path = docs.write_text(
            f"discovery/{round_num:02d}_question.md",
            f"---\ndoc: discovery\nstatus: open\nowner: user\n---\n\n# Discovery Question {round_num:02d}\n\n{question}\n",
        )
        self._record_document(iteration_id, f"discovery_question_{round_num:02d}", question_path)
        self._add_event(
            iteration_id,
            event_type="discovery.question",
            payload={
                "round": round_num,
                "question": question,
                "options": artifact.options,
                "assumptions": artifact.assumptions,
            },
        )
        self._node_event(
            iteration_id,
            "node.progress",
            NodeName.planner_discovery.value,
            "等待您的回答",
            question,
            severity="info",
            run_id=run_id,
            action_hint="在工作台回答该问题，或选择跳过澄清。",
        )
        self._update_iteration(
            iteration_id,
            status=IterationStatus.awaiting_requirements_input.value,
            current_node=None,
        )
        return {
            "route": "ask",
            "requirements_brief": artifact.requirements_brief,
            "pending_discovery_question": question,
            "pending_discovery_options": artifact.options,
            "pending_discovery_assumptions": artifact.assumptions,
            "status": IterationStatus.awaiting_requirements_input.value,
            "current_node": None,
        }

    def _requirements_input_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        question = state.get("pending_discovery_question") or ""
        options = list(state.get("pending_discovery_options") or [])
        assumptions = list(state.get("pending_discovery_assumptions") or [])
        answer = interrupt(
            {
                "checkpoint": "requirements_input",
                "iteration_id": iteration_id,
                "question": question,
                "options": options,
                "assumptions": assumptions,
            }
        )
        discovery_qa = list(state.get("discovery_qa") or [])
        round_num = len(discovery_qa) + 1
        discovery_qa.append(
            {
                "round": round_num,
                "question": question,
                "answer": str(answer),
                "options": options,
            }
        )
        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        answer_path = docs.write_text(
            f"discovery/{round_num:02d}_answer.md",
            f"---\ndoc: discovery\nstatus: answered\nowner: user\n---\n\n# Discovery Answer {round_num:02d}\n\n{answer}\n",
        )
        self._record_document(iteration_id, f"discovery_answer_{round_num:02d}", answer_path)
        self._add_event(
            iteration_id,
            event_type="discovery.answered",
            payload={"round": round_num, "question": question, "answer": str(answer)},
        )
        self._update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.planner_discovery.value)
        return {
            "discovery_qa": discovery_qa,
            "pending_discovery_question": None,
            "pending_discovery_options": [],
            "pending_discovery_assumptions": [],
            "status": IterationStatus.planning.value,
            "route": "",
            "current_node": NodeName.planner_discovery.value,
        }

    def _design_approval_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.awaiting_design_approval.value, current_node=None)
        self._add_event(iteration_id, event_type="design.pending", payload={"checkpoint": "design_approval"})
        self._node_event(
            iteration_id,
            "node.progress",
            "design_approval",
            "等待设计审批",
            "规划文档已生成，请审阅系统设计、修改计划与测试方案后批准进入实现。",
            severity="info",
            action_hint="在工作台批准设计，或停止迭代后修改 Epic/文档。",
        )
        answer = interrupt({"checkpoint": "design_approval", "iteration_id": iteration_id})
        self._add_event(iteration_id, event_type="design.approved", payload={"note": answer})
        self._node_event(
            iteration_id,
            "node.completed",
            "design_approval",
            "设计已批准",
            "用户已批准本轮规划，进入实现。",
            severity="success",
        )
        return {
            "design_approval": str(answer),
            "status": IterationStatus.coding.value,
            "current_node": None,
        }

    def _planner_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        goal = state["goal"]
        self._update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.planner.value, last_error=None)
        self._reset_live_cli(iteration_id, NodeName.planner.value)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.planner.value,
            "规划节点已启动",
            "正在读取大需求并拆分任务，准备生成系统设计、修改计划和测试。",
        )
        self._add_event(iteration_id, event_type="iteration.started", payload={"status": "planning"})
        run_result = self._execute(
            state,
            self._planner_command(state),
            node=NodeName.planner.value,
        )
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.planner.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.planner.value, "规划失败", "Planner CLI 执行失败。", severity="error", run_id=run_id, action_hint="查看运行日志，确认 claude CLI 可用并能返回 JSON artifact。")
            return self._block(iteration_id, "planner.failed", run_id, run_result.stderr)

        try:
            self._node_event(iteration_id, "node.progress", NodeName.planner.value, "正在解析规划产物", "已收到 Planner 输出，正在校验 JSON artifact 并写入文档。", run_id=run_id)
            artifact = self._planner_artifact(state, run_result)
            docs = IterationDocs(self.docs_root(iteration_id))
            docs.ensure()
            self._write_planner_artifact(iteration_id, docs, artifact, run_id=run_id)
            baseline = test_integrity_manifest(docs.root)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.coding.value,
                current_node=None,
                test_integrity_baseline=baseline,
                last_error=None,
            )
            self._add_event(iteration_id, event_type="planner.completed", payload={"documents": 3 + len(artifact.tests), "run_id": run_id})
            self._node_event(
                iteration_id,
                "node.completed",
                NodeName.planner.value,
                "规划完成",
                f"已根据澄清后的需求生成 3 份规划文档和 {len(artifact.tests)} 个测试文件，等待设计审批。",
                severity="success",
                run_id=run_id,
            )
            return {
                "status": IterationStatus.planning.value,
                "current_node": None,
                "planner_run_id": run_id,
                "route": "approval",
            }
        except Exception as exc:
            event_type = ui_spec_error_type(str(exc))
            hint = (
                "检查 tests/ui/*.json 是否使用 snake_case 动作名，并符合 UITestSpec schema。"
                if event_type == "ui_spec.invalid"
                else "查看 Planner 原始日志，要求模型只输出符合 schema 的 JSON。"
            )
            title = "UI 测试规格无效" if event_type == "ui_spec.invalid" else "规划产物无效"
            body = "Planner 写入了无法执行的 UI trajectory。" if event_type == "ui_spec.invalid" else "Planner 输出无法被解析为合法 artifact。"
            self._node_event(iteration_id, "node.failed", NodeName.planner.value, title, body, severity="error", run_id=run_id, action_hint=hint)
            return self._block(iteration_id, event_type, run_id, str(exc))

    def _coder_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        retry_counts = dict(state.get("retry_counts") or {})
        is_retry = retry_counts.get("coder_tester", 0) > 0
        self._update_iteration(
            iteration_id,
            status=IterationStatus.retrying.value if is_retry else IterationStatus.coding.value,
            current_node=NodeName.coder.value,
            retry_counts=retry_counts,
            last_error=None,
        )
        self._reset_live_cli(iteration_id, NodeName.coder.value)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.coder.value,
            "实现节点已启动" if not is_retry else "实现节点正在重试",
            "Coder 正在根据规划产出的规格修改代码。" if not is_retry else "Coder 正在根据上一轮失败信息修复实现。",
        )
        run_result = self._execute(
            state,
            self._coder_command(state),
            node=NodeName.coder.value,
        )
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.coder.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.coder.value, "实现失败", "Coder CLI 执行失败。", severity="error", run_id=run_id, action_hint="查看运行日志，确认 claude CLI 和工作区权限。")
            return self._block(iteration_id, "coder.failed", run_id, run_result.stderr)

        try:
            self._node_event(iteration_id, "node.progress", NodeName.coder.value, "正在解析实现结果", "已收到 Coder 输出，正在读取变更摘要和澄清请求。", run_id=run_id)
            artifact = self._coder_artifact(state, run_result)
        except Exception as exc:
            self._node_event(iteration_id, "node.failed", NodeName.coder.value, "实现产物无效", "Coder 输出无法被解析为合法 artifact。", severity="error", run_id=run_id, action_hint="查看 Coder 原始日志，要求模型只输出符合 schema 的 JSON。")
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

        if artifact.clarification_request:
            self._node_event(iteration_id, "node.progress", NodeName.coder.value, "实现需要澄清", artifact.clarification_request, severity="warning", run_id=run_id, action_hint="等待 Planner 澄清或人工补充决策。")
            return {"route": "clarification", "clarification_request": artifact.clarification_request, "coder_run_id": run_id}

        if not self._is_real_cli(state.get("mode")):
            src_root = self.project_root(iteration_id) / "src"
            src_root.mkdir(parents=True, exist_ok=True)
            app_file = src_root / "app.py"
            app_file.write_text(
                """from __future__ import annotations\n\n\ndef build_summary(goal: str) -> str:\n    return f'SpecForge prepared: {goal}'\n""",
                encoding="utf-8",
            )
            artifact.changed_paths.append(str(app_file.relative_to(self.project_root(iteration_id))))

        self._add_event(
            iteration_id,
            event_type="coder.completed",
            payload={"changed_paths": artifact.changed_paths, "summary": artifact.summary, "run_id": run_id},
        )
        self._node_event(iteration_id, "node.completed", NodeName.coder.value, "实现完成", artifact.summary or "代码实现已完成，准备进入测试完整性检查。", severity="success", run_id=run_id)
        return {"status": IterationStatus.testing.value, "route": "", "current_node": NodeName.integrity_check.value, "coder_run_id": run_id}

    def _planner_clarification_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        retry_counts = self._increment_count(state, "coder_planner_clarify")
        if retry_counts["coder_planner_clarify"] > state.get("max_clarifications", 3):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "clarification.max_retries", None, state.get("clarification_request") or "clarification cap reached", blocked_user=True)

        clarification_request = state.get("clarification_request") or ""
        self._prepare_iteration_docs(iteration_id)
        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        count = retry_counts["coder_planner_clarify"]
        question_path = docs.write_text(
            f"clarifications/{count:02d}_question.md",
            f"---\ndoc: clarification\nstatus: open\nowner: node2\n---\n\n# Clarification Request {count:02d}\n\n{clarification_request}\n",
        )
        self._record_document(iteration_id, f"clarification_question_{count:02d}", question_path)

        self._update_iteration(
            iteration_id,
            status=IterationStatus.retrying.value,
            current_node=NodeName.planner_clarification.value,
            retry_counts=retry_counts,
        )
        self._reset_live_cli(iteration_id, NodeName.planner_clarification.value)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.planner_clarification.value,
            "Planner 澄清节点已启动",
            "Planner 正在根据 Coder 的澄清请求生成正式回答。",
        )

        run_result = self._execute(
            state,
            self._planner_clarification_command(state, clarification_request),
            node=NodeName.planner_clarification.value,
        )
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.planner_clarification.value, run_result)
        if run_result.returncode:
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.planner_clarification.value,
                "Planner 澄清失败",
                "Planner CLI 未能回答 Coder 的澄清请求。",
                severity="error",
                run_id=run_id,
                action_hint="查看 Planner 原始日志，确认 claude CLI 可用。",
            )
            return self._block(iteration_id, "planner_clarification.failed", run_id, self._format_cli_failure(run_result))

        try:
            artifact = self._planner_clarification_artifact(state, run_result)
        except Exception as exc:
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.planner_clarification.value,
                "澄清产物无效",
                "Planner 澄清输出无法被解析为合法 artifact。",
                severity="error",
                run_id=run_id,
            )
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

        answer_path = docs.write_text(
            f"clarifications/{count:02d}_answer.md",
            f"---\ndoc: clarification\nstatus: answered\nowner: node1\n---\n\n# Clarification Answer {count:02d}\n\n{artifact.answer}\n",
        )
        self._record_document(iteration_id, f"clarification_answer_{count:02d}", answer_path)
        self._add_event(
            iteration_id,
            event_type="clarification.answered",
            payload={"request": clarification_request, "count": count, "answer": artifact.answer},
        )
        self._node_event(
            iteration_id,
            "node.completed",
            NodeName.planner_clarification.value,
            "Planner 已回答澄清",
            artifact.summary or "Planner 已生成澄清回答，系统将回到实现节点。",
            severity="success",
            run_id=run_id,
        )
        return {
            "status": IterationStatus.coding.value,
            "route": "",
            "failure_notes": artifact.answer,
            "clarification_request": None,
            "retry_counts": retry_counts,
        }

    def _integrity_check_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.integrity_check.value)
        self._node_event(iteration_id, "node.started", NodeName.integrity_check.value, "测试完整性检查已启动", "正在确认 Planner 写入的受保护测试没有被实现节点修改。")
        problems = self._integrity_problems(iteration_id)
        if problems:
            self._node_event(iteration_id, "node.failed", NodeName.integrity_check.value, "测试完整性失败", "; ".join(problems), severity="error", action_hint="恢复受保护测试文件，或重新运行 Planner 生成新的测试基线。")
            return self._block(iteration_id, "test_integrity.failed", None, "; ".join(problems))
        self._add_event(iteration_id, event_type="test_integrity.passed", payload={"stage": "before_tester"})
        self._node_event(iteration_id, "node.completed", NodeName.integrity_check.value, "测试完整性通过", "受保护测试未被未授权修改，可以进入独立验证。", severity="success")
        return {"status": IterationStatus.testing.value, "current_node": NodeName.tester.value}

    def _tester_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.tester.value, last_error=None)
        self._reset_live_cli(iteration_id, NodeName.tester.value)
        self._publish_snapshot(iteration_id)
        self._node_event(iteration_id, "node.started", NodeName.tester.value, "验证节点已启动", "Tester 正在独立运行验证并准备交付建议。")
        run_result = self._execute(state, self._tester_command(state), node=NodeName.tester.value)
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.tester.value, run_result)
        try:
            artifact: TesterArtifact | None = None
            if run_result.returncode:
                artifact = self._try_tester_artifact(state, run_result)
                if artifact is not None:
                    self._node_event(
                        iteration_id,
                        "tester.nonzero_artifact.accepted",
                        NodeName.tester.value,
                        "验证命令异常但产物可用",
                        "Tester CLI 非零退出，但输出了合法验证产物；系统将继续处理报告并把异常记录为警告。",
                        severity="warning",
                        run_id=run_id,
                        action_hint="检查 Tester 原始日志，确认非零退出是否只来自自动化工具环境问题。",
                    )
                else:
                    primary_notes = self._tester_failure_notes(run_result)
                    self._node_event(
                        iteration_id,
                        "tester.review_fallback.started",
                        NodeName.tester.value,
                        "启动代码审查兜底",
                        "Tester 自动化验证未能产出合法报告，正在改用禁止 UI 自动化的独立审查。",
                        severity="warning",
                        run_id=run_id,
                        action_hint="Playwright/CUA 等工具不可用不会直接阻断；兜底报告会记录未执行项。",
                    )
                    review_result = self._execute(
                        state,
                        self._tester_command(state, review_only=True, fallback_reason=primary_notes),
                        node=NodeName.tester.value,
                    )
                    if self._is_iteration_gone(iteration_id):
                        return self._abort_state()
                    review_run_id = self._record_run(iteration_id, NodeName.tester.value, review_result)
                    run_id = review_run_id
                    if review_result.returncode:
                        notes = self._tester_failure_notes(run_result, review_result)
                        self._node_event(
                            iteration_id,
                            "tester.review_fallback.failed",
                            NodeName.tester.value,
                            "代码审查兜底失败",
                            notes,
                            severity="error",
                            run_id=review_run_id,
                            action_hint="查看 Tester 两次运行日志；若是实现问题将进入自动修复回环。",
                        )
                        return self._route_tester_failure(
                            state,
                            review_run_id,
                            TesterArtifact(
                                verify_report="# Verify Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
                                passed=False,
                                failure_notes=notes,
                            ),
                        )
                    artifact = self._tester_artifact(state, review_result)
                    self._augment_review_fallback_artifact(artifact, primary_notes)
                    self._node_event(
                        iteration_id,
                        "tester.review_fallback.completed",
                        NodeName.tester.value,
                        "代码审查兜底完成",
                        "Tester 已在不调用浏览器或原生自动化工具的前提下完成独立审查。",
                        severity="success",
                        run_id=review_run_id,
                    )
            else:
                self._node_event(iteration_id, "node.progress", NodeName.tester.value, "正在解析验证结果", "已收到 Tester 输出，正在校验验证报告、交付建议和对抗测试。", run_id=run_id)
                artifact = self._tester_artifact(state, run_result)
            if artifact is None:
                raise ValueError("tester artifact was not resolved")
            problems = self._integrity_problems(iteration_id)
            if problems:
                self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证前测试完整性失败", "; ".join(problems), severity="error", run_id=run_id, action_hint="检查测试目录是否被实现节点修改。")
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            docs = IterationDocs(self.docs_root(iteration_id))
            ui_result = self._run_ui_specs(iteration_id, docs, run_id=run_id)
            if ui_result.results:
                artifact.ui_results.extend(ui_result.results)
                artifact.ux_notes.extend(self._ui_observations(ui_result))
            if ui_result.fallback == "playwright":
                self._add_event(
                    iteration_id,
                    event_type="ui_driver.fallback",
                    payload={"fallback": ui_result.fallback, "count": len(ui_result.results)},
                )
            if ui_result.warning:
                artifact.ui_warnings.append(ui_result.warning)
                has_native_warning = any(
                    result.status == "warning" and result.kind == "native" for result in ui_result.results
                )
                if has_native_warning or not ui_result.fallback:
                    artifact.delivery_recommendations.append(f"部分 UI 未执行: {ui_result.warning}")
                self._add_event(iteration_id, event_type="ui_driver.warning", payload={"warning": ui_result.warning})
            elif ui_result.results:
                self._add_event(iteration_id, event_type="ui_driver.completed", payload={"count": len(ui_result.results)})
            if any(result.status == "failed" for result in ui_result.results):
                failed_results = [result for result in ui_result.results if result.status == "failed"]
                failed_summary = "; ".join(f"{result.title or result.id}: {result.error or 'failed'}" for result in failed_results)
                warning = f"UI 自动化测试失败，已降级为警告: {failed_summary}"
                artifact.ui_warnings.append(warning)
                artifact.delivery_recommendations.append("UI 自动化存在失败项；本轮是否通过以 Tester 代码审查未发现 P0/P1 缺陷为准，交付前建议人工复核失败 UI 场景。")
                self._add_event(
                    iteration_id,
                    event_type="ui_driver.failed",
                    payload={"failed": [result.model_dump() for result in failed_results], "blocking": False},
                )
            self._write_tester_artifact(iteration_id, docs, artifact, run_id=run_id)
            gate_ok, gate_msg = self._run_artifact_gate(state)
            if not gate_ok:
                self._rollback_tester_adversarial(iteration_id, artifact.adversarial_tests)
                artifact = self._gate_failed_artifact(artifact, gate_msg)
                self._node_event(
                    iteration_id,
                    "node.failed",
                    NodeName.tester.value,
                    "验证产物未通过写盘闸门",
                    gate_msg,
                    severity="error",
                    run_id=run_id,
                    action_hint="Tester 将自修 adversarial 或验证产物，无需 Coder 改 src。",
                )
                return self._route_tester_failure(state, run_id, artifact)
            problems = self._integrity_problems(iteration_id)
            if problems:
                self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证后测试完整性失败", "; ".join(problems), severity="error", run_id=run_id, action_hint="Tester 只能写入 adversarial 和 UI recordings；请检查异常测试文件。")
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            if not artifact.passed:
                notes = summarize_failure_notes(self._normalize_tester_artifact(artifact))
                self._node_event(
                    iteration_id,
                    "node.failed",
                    NodeName.tester.value,
                    "验证未通过",
                    notes,
                    severity="error",
                    run_id=run_id,
                    action_hint="查看失败说明，等待按写权限分区自动重试或处理阻断。",
                )
                return self._route_tester_failure(state, run_id, artifact)
            self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
            self._add_event(iteration_id, event_type="tester.completed", payload={"result": "passed", "run_id": run_id})
            self._node_event(iteration_id, "node.completed", NodeName.tester.value, "验证通过", "验证报告和交付建议已生成，等待规格复核和最终确认。", severity="success", run_id=run_id)
            return {"status": IterationStatus.awaiting_verify_approval.value, "route": "", "current_node": None, "tester_run_id": run_id}
        except Exception as exc:
            event_type = ui_spec_error_type(str(exc))
            hint = (
                "检查 tests/ui/*.json 动作名与字段是否符合 UITestSpec schema。"
                if event_type == "ui_spec.invalid"
                else "查看 Tester 原始日志，要求模型只输出符合 schema 的 JSON。"
            )
            title = "UI 测试规格无效" if event_type == "ui_spec.invalid" else "验证产物无效"
            body = "受保护 UI trajectory 无法被 UI Driver 加载。" if event_type == "ui_spec.invalid" else "Tester 输出无法被解析为合法 artifact。"
            self._node_event(iteration_id, "node.failed", NodeName.tester.value, title, body, severity="error", run_id=run_id, action_hint=hint)
            return self._block(iteration_id, event_type, run_id, str(exc))

    def _planner_verify_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.planner_verify.value)
        self._node_event(iteration_id, "node.started", NodeName.planner_verify.value, "规格复核已启动", "Planner 正在机械检查验证报告是否满足基本结构要求。")
        docs = IterationDocs(self.docs_root(iteration_id))
        try:
            text = docs.read_text("verify_report.md")
            if "# " not in text or "Pass" not in text:
                raise ValueError("verify_report missing required summary markers")
        except Exception as exc:
            retry_counts = self._increment_count(state, "planner_verify_reject")
            if retry_counts["planner_verify_reject"] > state.get("max_verify_rejects", 2):
                self._update_iteration(iteration_id, retry_counts=retry_counts)
                self._node_event(iteration_id, "node.failed", NodeName.planner_verify.value, "规格复核驳回已达上限", str(exc), severity="error", action_hint="需要人工检查验证报告或修改 Tester 输出。")
                return self._block(iteration_id, "planner_verify.max_retries", None, str(exc))
            self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=NodeName.planner_verify.value, retry_counts=retry_counts, last_error=str(exc))
            self._add_event(iteration_id, event_type="planner_verify.rejected", payload={"reason": str(exc), "count": retry_counts["planner_verify_reject"]})
            self._node_event(iteration_id, "node.progress", NodeName.planner_verify.value, "规格复核驳回", str(exc), severity="warning", action_hint="系统将回到实现/验证回环修复验证报告。")
            return {"route": "verify_rejected", "failure_notes": str(exc), "retry_counts": retry_counts}
        self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
        self._add_event(iteration_id, event_type="planner_verify.accepted", payload={"report": "verify_report"})
        self._node_event(iteration_id, "node.completed", NodeName.planner_verify.value, "规格复核通过", "验证报告结构满足要求，可以进入最终确认。", severity="success", document="verify_report")
        return {"status": IterationStatus.awaiting_verify_approval.value, "current_node": None}

    def _verify_approval_node(self, state: PipelineState) -> PipelineState:
        answer = interrupt({"checkpoint": "verify", "iteration_id": state["iteration_id"]})
        self._add_event(state["iteration_id"], event_type="verify.approved", payload={"note": answer})
        self._node_event(state["iteration_id"], "node.completed", "verify_approval", "验证结果已确认", "用户已确认本轮验证结果，准备交付。", severity="success")
        return {"verify_approval": str(answer), "status": IterationStatus.delivered.value}

    def _done_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        row = self._require_iteration(iteration_id)
        self._update_iteration(iteration_id, status=IterationStatus.delivered.value, current_node=None, last_error=None)
        append_iteration_log(
            self.project_repo_root(iteration_id),
            docs_slug=row["docs_slug"] if "docs_slug" in row.keys() and row["docs_slug"] else iteration_id,
            event="iteration.delivered",
            detail=f"Iteration delivered after goal: {row['goal']}",
        )
        self._add_event(iteration_id, event_type="iteration.delivered", payload={"status": "delivered"})
        self._node_event(iteration_id, "node.completed", "done", "迭代已交付", "本轮流水线已完成并归档为已交付状态。", severity="success")
        return {"status": IterationStatus.delivered.value, "current_node": None}

    def _route_after_discovery(self, state: PipelineState) -> Literal["blocked", "ask", "ready"]:
        if state.get("status") in {
            IterationStatus.blocked.value,
            IterationStatus.blocked_user.value,
            IterationStatus.stopped.value,
        }:
            return "blocked"
        if state.get("route") == "ask":
            return "ask"
        return "ready"

    def _route_after_planner(self, state: PipelineState) -> Literal["blocked", "approval"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        return "approval"

    def _route_after_design_approval(self, state: PipelineState) -> Literal["blocked", "coder"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        return "coder"

    def _route_after_coder(self, state: PipelineState) -> Literal["blocked", "clarification", "integrity"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "clarification":
            return "clarification"
        return "integrity"

    def _route_after_clarification(self, state: PipelineState) -> Literal["blocked", "coder"]:
        return "blocked" if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value, IterationStatus.stopped.value} else "coder"

    def _route_after_integrity(self, state: PipelineState) -> Literal["blocked", "tester"]:
        return "blocked" if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value} else "tester"

    def _route_after_tester(self, state: PipelineState) -> Literal["blocked", "retry", "self_retry", "verify"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "self_retry":
            return "self_retry"
        if state.get("route") == "retry":
            return "retry"
        return "verify"

    def _route_after_planner_verify(self, state: PipelineState) -> Literal["blocked", "tester", "approval"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "verify_rejected":
            return "tester"
        return "approval"

    def _config(self, iteration_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": iteration_id}}

    def _begin_invoke(self, iteration_id: str) -> None:
        self._invoking.add(iteration_id)

    def _end_invoke(self, iteration_id: str) -> None:
        self._invoking.discard(iteration_id)

    @staticmethod
    def _format_cli_failure(run_result: CLIResult) -> str:
        stderr = (run_result.stderr or "").strip()
        if stderr:
            return stderr
        if run_result.returncode == 127:
            return f"CLI 命令未找到：{' '.join(run_result.command)}"
        if run_result.returncode != 0:
            return f"CLI 退出码 {run_result.returncode}，未捕获 stderr 输出。"
        return "CLI 执行失败，未返回错误详情。"

    def _require_iteration(self, iteration_id: str):
        row = self.db.get_iteration_row(iteration_id)
        if row is None:
            raise KeyError(iteration_id)
        return row

    def _is_iteration_gone(self, iteration_id: str) -> bool:
        if iteration_id in self._aborted_iterations:
            return True
        return self.db.get_iteration_row(iteration_id) is None

    def _abort_state(self) -> PipelineState:
        return {"status": IterationStatus.stopped.value, "route": "", "current_node": None}

    def _record_run(self, iteration_id: str, node: str, run_result: CLIResult) -> str:
        run_id = self.db.add_run(
            iteration_id,
            node=node,
            status="failed" if run_result.returncode else "success",
            command=" ".join(run_result.command),
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            exit_code=run_result.returncode,
            finished_at=iso(utcnow()),
        )
        self._clear_live_cli(iteration_id)
        self._publish_snapshot(iteration_id)
        return run_id

    def _record_document(self, iteration_id: str, name: str, path: Path) -> None:
        self.db.add_document(iteration_id, name=name, path=str(path), checksum=checksum(path))

    def _update_iteration(self, iteration_id: str, **fields: Any) -> None:
        self.db.update_iteration(iteration_id, **fields)
        self._publish_snapshot(iteration_id)

    def _add_event(self, iteration_id: str, *, event_type: str, payload: dict[str, Any]) -> None:
        event = self.db.add_event(iteration_id, event_type=event_type, payload=payload)
        event_payload = {
            "id": event["id"],
            "iteration_id": event["iteration_id"],
            "type": event["type"],
            "payload": json.loads(event["payload"]),
            "created_at": event["created_at"],
        }
        self.broker.publish(iteration_id, EventEnvelope(type="event", event=event_payload, snapshot=self.dashboard_snapshot(iteration_id)))

    def _publish_snapshot(self, iteration_id: str) -> None:
        try:
            self.broker.publish(iteration_id, EventEnvelope(type="snapshot", snapshot=self.dashboard_snapshot(iteration_id)))
        except Exception:
            pass

    def _block(self, iteration_id: str, event_type: str, run_id: Optional[str], reason: str, *, blocked_user: bool = False) -> PipelineState:
        status = IterationStatus.blocked_user.value if blocked_user else IterationStatus.blocked.value
        self._update_iteration(iteration_id, status=status, current_node=None, last_error=reason)
        payload: dict[str, Any] = {"stderr": reason}
        if run_id:
            payload["run_id"] = run_id
        self._add_event(iteration_id, event_type=event_type, payload=payload)
        self._node_event(
            iteration_id,
            "error.classified",
            "system",
            self._error_title(event_type),
            reason,
            severity="error",
            run_id=run_id,
            action_hint=self._error_action_hint(event_type),
        )
        return {"status": status, "route": "", "current_node": None, "blocked_reason": reason}

    def _execute(
        self,
        state: PipelineState,
        command: list[str],
        *,
        node: str | None = None,
    ) -> CLIResult:
        runner = self.real_runner if self._is_real_cli(state.get("mode")) else self.dry_runner
        iteration_id = state["iteration_id"]
        if node is None:
            row = self._require_iteration(iteration_id)
            current_node = row["current_node"] or "agent"
        else:
            current_node = node
        self._reset_live_cli(iteration_id, current_node)
        self._publish_snapshot(iteration_id)
        seen_output = {"stdout": False, "stderr": False}
        seen_cli_events: set[str] = set()

        def on_output(stream: str, chunk: str) -> None:
            if not chunk:
                return
            self._append_live_cli(iteration_id, stream, chunk)
            self._maybe_publish_live_cli(iteration_id)
            if not chunk.strip():
                return
            if self._is_real_cli(state.get("mode")):
                cli_events = self.cli_presenter.present_chunk(chunk, node=str(current_node))
                for event in cli_events:
                    key = event.key
                    if key in seen_cli_events and event.phase not in ("text", "thinking"):
                        continue
                    if event.phase not in ("text", "thinking"):
                        seen_cli_events.add(key)
                    self._cli_display_event(iteration_id, event)
                if cli_events:
                    return
            if seen_output[stream]:
                return
            seen_output[stream] = True
            if stream == "stdout":
                title = "已收到模型输出"
                message = "Agent CLI 正在输出内容，可在下方实时日志查看。"
            else:
                title = "CLI 诊断输出"
                message = "CLI 向 stderr 输出了附加日志，可在实时日志查看。"
            self._node_event(
                iteration_id,
                "node.progress",
                str(current_node),
                title,
                message,
                severity="info",
            )

        try:
            return runner.run(
                command,
                cwd=self._execution_cwd(state),
                on_output=on_output,
                iteration_id=iteration_id,
            )
        finally:
            if not self._is_iteration_gone(iteration_id):
                self._publish_snapshot(iteration_id)

    def _cli_display_event(self, iteration_id: str, event: CliDisplayEvent) -> None:
        self._add_event(iteration_id, event_type="cli.display", payload=event.payload())

    def _is_real_cli(self, mode: Optional[str]) -> bool:
        return mode == Mode.real_cli.value or settings.mode == Mode.real_cli.value

    def _execution_cwd(self, state: PipelineState) -> Path:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            return self.project_repo_root(iteration_id)
        return self.project_root(iteration_id)

    def _workflow_state_section(self, state: PipelineState, *, node: str) -> str:
        current = state.get("current_node") or node
        status = state.get("status") or ""
        route = state.get("route") or ""
        parts = [f"node: {current}", f"status: {status}"]
        if route:
            parts.append(f"route: {route}")
        body = "\n".join(parts)
        return f"<workflow-state>\n{body}\n</workflow-state>"

    def _context_manifest_prompt(self, iteration_id: str, manifest_rel: str, *, heading: str) -> str:
        path = self.docs_root(iteration_id) / manifest_rel
        if not path.exists():
            return ""
        from .context_manifest import read_jsonl

        return format_manifest_for_prompt(read_jsonl(path), heading=heading)

    def _runtime_notes_prompt(self, iteration_id: str) -> str:
        path = self.docs_root(iteration_id) / RUNTIME_NOTES
        return format_runtime_notes_section(path)

    def add_runtime_note(self, iteration_id: str, note: str, *, node: str = "user") -> None:
        text = note.strip()
        if not text:
            return
        docs_root = self.docs_root(iteration_id)
        append_runtime_note(docs_root / RUNTIME_NOTES, note=text, node=node)
        self._add_event(
            iteration_id,
            event_type="runtime.note",
            payload={"note": text, "node": node},
        )
        self._publish_snapshot(iteration_id)

    def _project_convention_prompt(self, repo_root: Path) -> str:
        convention = read_convention_excerpt(repo_root)
        if not convention:
            return ""
        return f"Project docs/00_convention.md:\n{convention}\n"

    def _spec_index_prompt(self, repo_root: Path) -> str:
        index = read_spec_index(repo_root)
        if not index:
            return ""
        return f"Project docs/spec-index.md:\n{index}\n"

    def _planner_brief(self, state: PipelineState) -> str:
        iteration_id = state["iteration_id"]
        docs_root = self.docs_root(iteration_id)
        repo_root = self.project_repo_root(iteration_id)
        parts = [
            f"Iteration goal: {state['goal']}",
            f"Project docs root: {repo_root / 'docs'}",
            f"Iteration docs root: {docs_root}",
            "Read docs/00_convention.md and docs/01_project_goal.md before planning. "
            "If docs/00_convention.md is still the default stub, update it with this repo's source/test layout (real-cli) or record layout in system_design. "
            "If docs/03_invariants/ or docs/04_decisions/ exist, read relevant entries; create them only when needed. "
            "If docs/spec-index.md exists, honor it when building context manifests.",
        ]
        if state.get("epic_title"):
            parts.append(f"Epic title: {state['epic_title']}")
        if state.get("epic_description"):
            parts.append(f"Epic description: {state['epic_description']}")
        if state.get("epic_acceptance_criteria"):
            parts.append(f"Epic acceptance criteria: {state['epic_acceptance_criteria']}")
        return "\n".join(parts)

    def _discovery_context_prompt(self, state: PipelineState) -> str:
        parts: list[str] = []
        brief = (state.get("requirements_brief") or "").strip()
        if brief:
            parts.append(f"Current requirements brief:\n{brief}")
        qa_text = self._format_discovery_qa_for_prompt(state.get("discovery_qa") or [])
        if qa_text:
            parts.append(f"Prior discovery Q&A:\n{qa_text}")
        if not parts:
            return "(no prior discovery context)"
        return "\n\n".join(parts)

    @staticmethod
    def _format_discovery_qa_for_prompt(discovery_qa: list[dict[str, Any]]) -> str:
        if not discovery_qa:
            return ""
        lines: list[str] = []
        for item in discovery_qa:
            round_num = item.get("round", "?")
            question = item.get("question", "")
            answer = item.get("answer", "")
            lines.append(f"Round {round_num} Q: {question}")
            lines.append(f"Round {round_num} A: {answer}")
        return "\n".join(lines)

    @staticmethod
    def _discovery_brief_markdown(brief: str, assumptions: list[str], complexity: str) -> str:
        assumption_lines = "\n".join(f"- {item}" for item in assumptions) if assumptions else "- (none)"
        body = brief.strip() or "(evolving)"
        return (
            "---\ndoc: requirements_brief\nstatus: draft\nowner: user\n---\n\n"
            f"# Requirements Brief\n\n**Complexity:** {complexity}\n\n## Summary\n\n{body}\n\n"
            f"## Assumptions\n\n{assumption_lines}\n"
        )

    def _discovery_snapshot_fields(self, iteration_id: str) -> dict[str, Any]:
        graph_state = self.graph.get_state(self._config(iteration_id))
        values = graph_state.values or {}
        discovery_qa = list(values.get("discovery_qa") or [])
        history = [
            {
                "round": int(item.get("round", index + 1)),
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
            }
            for index, item in enumerate(discovery_qa)
        ]
        pending: dict[str, Any] | None = None
        question = values.get("pending_discovery_question")
        if question:
            pending = {
                "round": len(discovery_qa) + 1,
                "question": str(question),
                "options": list(values.get("pending_discovery_options") or []),
                "assumptions": list(values.get("pending_discovery_assumptions") or []),
            }
        return {"pending_discovery": pending, "discovery_history": history}

    def _cli_provider(self, state: PipelineState, stage: CliStage) -> str:
        raw = self._project_field(state, "cli_bindings")
        bindings = parse_cli_bindings(raw)
        return resolve_cli_provider(bindings, stage)

    def _planner_discovery_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "planner_discovery",
                repo_root=repo_root,
                variables={
                    "schema_hint": (
                        "{status:ask|ready, complexity:trivial|simple|moderate|complex, "
                        "question?:string, options:[string] (required when ask; last must be 其他（请说明）), "
                        "assumptions:[string], "
                        "requirements_brief:string, rationale:string}"
                    ),
                    "brief": self._planner_brief(state),
                    "discovery_context": self._discovery_context_prompt(state),
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root) + self._spec_index_prompt(repo_root),
                    "workflow_state": self._workflow_state_section(state, node=NodeName.planner_discovery.value),
                },
            )
            provider = self._cli_provider(state, "planner_discovery")
            return build_planner_discovery_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PlannerDiscoveryArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "planner_discovery_artifact", PlannerDiscoveryArtifact),
            )
        return ["specforge", "planner_discovery", iteration_id]

    def _planner_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        brief = self._planner_brief(state)
        requirements_brief = (state.get("requirements_brief") or "").strip() or "(see iteration goal and discovery docs)"
        discovery_qa = self._format_discovery_qa_for_prompt(state.get("discovery_qa") or []) or "(none)"
        if self._is_real_cli(state.get("mode")):
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "planner",
                repo_root=repo_root,
                variables={
                    "schema_hint": (
                        "{system_design:string, modification_plan:string, testing_plan:string, "
                        "tests:[{path:string, content:string}], "
                        "context_for_coder:[{file:string, reason:string}], "
                        "context_for_tester:[{file:string, reason:string}]}"
                    ),
                    "ui_spec_hint": (
                        "{id,title,kind:web|native,target:{url|bundle_id|app_name},"
                        "steps:[{action,text,value,selector,key,keys,direction,amount}]}"
                    ),
                    "ui_actions": ", ".join(UI_TEST_ACTIONS),
                    "brief": brief,
                    "requirements_brief": requirements_brief,
                    "discovery_qa": discovery_qa,
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root) + self._spec_index_prompt(repo_root),
                    "workflow_state": self._workflow_state_section(state, node=NodeName.planner.value),
                },
            )
            provider = self._cli_provider(state, "planner")
            return build_planner_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PlannerArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "planner_artifact", PlannerArtifact),
            )
        return ["specforge", "planner", iteration_id]

    def _planner_clarification_command(self, state: PipelineState, clarification_request: str) -> list[str]:
        if self._is_real_cli(state.get("mode")):
            iteration_id = state["iteration_id"]
            docs_root = self.docs_root(iteration_id)
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "planner_clarification",
                repo_root=repo_root,
                variables={
                    "docs_root": str(docs_root),
                    "schema_hint": "{answer:string, summary:string}",
                    "clarification_request": clarification_request,
                    "context_manifest": self._context_manifest_prompt(
                        iteration_id,
                        FOR_CODER,
                        heading="Coder context manifest (for_coder.jsonl):",
                    ),
                    "runtime_notes": self._runtime_notes_prompt(iteration_id),
                },
            )
            provider = self._cli_provider(state, "planner_clarification")
            return build_planner_clarification_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PlannerClarificationArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "planner_clarification_artifact", PlannerClarificationArtifact),
            )
        return ["specforge", "planner_clarification", state["iteration_id"]]

    def _coder_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            notes = state.get("failure_notes") or ""
            docs_root = self.docs_root(iteration_id)
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "coder",
                repo_root=repo_root,
                variables={
                    "docs_root": str(docs_root),
                    "schema_hint": "{changed_paths:[string], summary:string, clarification_request?:string}",
                    "failure_notes": notes or "(none)",
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root),
                    "context_manifest": self._context_manifest_prompt(
                        iteration_id,
                        FOR_CODER,
                        heading="Required context files (read only these paths):",
                    ),
                    "runtime_notes": self._runtime_notes_prompt(iteration_id),
                },
            )
            provider = self._cli_provider(state, "coder")
            return build_coder_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(CoderArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "coder_artifact", CoderArtifact),
            )
        return ["specforge", "coder", iteration_id]

    def _tester_command(self, state: PipelineState, *, review_only: bool = False, fallback_reason: str = "") -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = self._tester_prompt(state, review_only=review_only, fallback_reason=fallback_reason)
            provider = self._cli_provider(state, "tester")
            return build_tester_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(TesterArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "tester_artifact", TesterArtifact),
            )
        return ["specforge", "tester", iteration_id]

    def _tester_prompt(self, state: PipelineState, *, review_only: bool, fallback_reason: str = "") -> str:
        iteration_id = state["iteration_id"]
        row = self._require_iteration(iteration_id)
        docs_root = self.docs_root(iteration_id)
        repo_root = self.project_repo_root(iteration_id)
        test_command = row["test_command"] if "test_command" in row.keys() else None
        build_command = row["build_command"] if "build_command" in row.keys() else None
        if not build_command and state.get("project_id"):
            build_command = self._project_field(state, "default_build_command")

        retry_notes_section = ""
        if state.get("failure_notes"):
            retry_notes_section = (
                "Retry notes to address in the Tester artifact: "
                f"{state.get('failure_notes')}. "
                "If Planner verification rejected verify_report.md structure, regenerate verify_report with a Markdown title, "
                "a Summary section, and explicit Pass/Fail counts; this is a Tester docs artifact, not a Coder src/** change."
            )

        if test_command:
            test_command_section = f"Configured test command: {test_command}. Run it when practical and report the result."
        else:
            test_command_section = (
                "No configured test command is set; choose lightweight verification from the repo when practical."
            )

        build_command_section = ""
        if build_command:
            build_command_section = (
                f"Configured build command: {build_command}. Run it when practical before marking passed=true."
            )

        if review_only:
            execution_mode = (
                "This is a review-only fallback after the primary Tester run failed before producing a valid artifact. "
                "Do not invoke Playwright, CUA Driver, browsers, native GUI automation, or screen recording tools. "
                "Base the verdict on code review, static inspection, available logs, and non-UI checks only. "
                "The pass/fail verdict must represent whether the code review found P0/P1 bugs. "
                "If UI automation was skipped because of the primary failure, include that in ui_warnings and delivery_recommendations. "
                f"Primary failure notes: {fallback_reason}"
            )
        else:
            execution_mode = (
                "Run verification and inspect user-facing behavior where possible. "
                "UI automation is best-effort evidence; UI automation failures should be reported as warnings, "
                "not as passed=false, unless your code review identifies a P0/P1 implementation bug behind them. "
                "Include practical post-delivery recommendations."
            )

        framework = read_framework_conventions()
        framework_block = f"SpecForge framework rules:\n{framework}\n" if framework else ""

        return compose_stage_prompt(
            "tester",
            repo_root=repo_root,
            variables={
                "repo_root": str(repo_root),
                "docs_root": str(docs_root),
                "schema_hint": (
                    "{verify_report:string, passed:boolean, failure_notes?:string, "
                    "defects:[{severity:'P0'|'P1'|'P2', path?:string, owner?:'coder'|'tester'|'planner', message:string}], "
                    "ux_notes:[string], delivery_recommendations:[string], "
                    "ui_results?:[], ui_warnings?:[], adversarial_tests:[{path:string, content:string}]}"
                ),
                "test_command_section": test_command_section,
                "build_command_section": build_command_section,
                "retry_notes_section": retry_notes_section,
                "framework_conventions": framework_block,
                "convention_excerpt": self._project_convention_prompt(repo_root),
                "context_manifest": self._context_manifest_prompt(
                    iteration_id,
                    FOR_TESTER,
                    heading="Required context files (read only these paths):",
                ),
                "runtime_notes": self._runtime_notes_prompt(iteration_id),
                "execution_mode": execution_mode,
            },
        )

    def _artifact_schema_inline(self, model: type[BaseModel]) -> str:
        return json.dumps(model.model_json_schema(), ensure_ascii=False)

    def _artifact_schema_file(self, iteration_id: str, name: str, model: type[BaseModel]) -> Path:
        schema_dir = self.project_root(iteration_id) / ".specforge" / "schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        path = schema_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _project_field(self, state: PipelineState, field: str) -> Optional[str]:
        project_id = state.get("project_id")
        if not project_id:
            return None
        project = self.db.get_project_row(project_id)
        if project is None:
            return None
        return project[field]

    def _planner_discovery_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerDiscoveryArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PlannerDiscoveryArtifact)  # type: ignore[return-value]
        discovery_qa = state.get("discovery_qa") or []
        goal = state["goal"]
        if not discovery_qa:
            return PlannerDiscoveryArtifact(
                status="ask",
                complexity="moderate",
                question=f"What is the primary acceptance criterion for: {goal}?",
                options=[
                    "Ship a minimal vertical slice first",
                    "Match existing product conventions exactly",
                    "Optimize for test coverage and CI gates",
                    "其他（请说明）",
                ],
                assumptions=["Dry-run discovery round 1"],
                requirements_brief=f"Goal: {goal}\n\n(Open questions remain.)",
                rationale="Dry-run asks one clarifying question before planning.",
            )
        return PlannerDiscoveryArtifact(
            status="ready",
            complexity="simple",
            assumptions=["User answered the dry-run discovery question"],
            requirements_brief=(
                f"Goal: {goal}\n\n"
                f"User answer: {discovery_qa[-1].get('answer', '')}\n\n"
                "Proceed to system design, modification plan, and protected tests."
            ),
            rationale="Dry-run discovery complete after one Q&A round.",
        )

    def _planner_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PlannerArtifact)  # type: ignore[return-value]
        goal = state["goal"]
        return PlannerArtifact(
            system_design=f"""---\ndoc: system_design\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - System Design\n\nGoal: {goal}\n\nThis dry-run design was produced by the LangGraph planner node.\n""",
            modification_plan="""---\ndoc: modification_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Modification Plan\n\n- Generate a minimal source module.\n- Preserve planner-authored tests.\n- Proceed directly to the coder node after planning.\n""",
            testing_plan="""---\ndoc: testing_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Testing Plan\n\n- T01: backend health endpoint responds.\n- T02: dry-run reaches delivery approval.\n- T03: delivered status requires final approval.\n""",
            tests=[
                ArtifactFile(
                    path="tests/unit/test_transitions.py",
                    content="from specforge.models import IterationStatus\n\n\ndef test_status_names_exist():\n    assert IterationStatus.created.value == 'created'\n",
                )
            ],
            context_for_coder=[
                ContextManifestEntry(file="system_design.md", reason="Approved design for Coder"),
                ContextManifestEntry(file="modification_plan.md", reason="Implementation scope"),
                ContextManifestEntry(file="testing_plan.md", reason="Protected test strategy"),
                ContextManifestEntry(file="tests/unit/test_transitions.py", reason="Protected unit test"),
            ],
            context_for_tester=[
                ContextManifestEntry(file="system_design.md", reason="Design intent for verification"),
                ContextManifestEntry(file="modification_plan.md", reason="Expected implementation scope"),
                ContextManifestEntry(file="testing_plan.md", reason="Verification strategy"),
                ContextManifestEntry(file="tests/unit/test_transitions.py", reason="Protected tests to respect"),
            ],
        )

    def _planner_clarification_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerClarificationArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PlannerClarificationArtifact)  # type: ignore[return-value]
        request = state.get("clarification_request") or "unspecified clarification"
        return PlannerClarificationArtifact(
            answer=f"Proceed with the approved spec. Clarification resolved: {request}",
            summary="Dry-run planner clarification answered the coder request.",
        )

    def _run_ui_specs(self, iteration_id: str, docs: IterationDocs, *, run_id: Optional[str] = None) -> UIDriverRunResult:
        specs = self._load_ui_specs(docs)
        if not specs:
            return UIDriverRunResult(available=True, results=[])
        self._node_event(iteration_id, "node.started", "ui_driver", "UI Driver 已启动", f"正在执行 {len(specs)} 条 UI trajectory。", run_id=run_id)
        self._add_event(iteration_id, event_type="ui_driver.started", payload={"count": len(specs)})
        result = self.ui_driver.run_specs(specs, docs.root, iteration_id=iteration_id)
        if result.cua_busy:
            holder = result.cua_session_holder or "another iteration"
            self._add_event(
                iteration_id,
                event_type="ui_driver.cua_busy",
                payload={"holder": holder, "count": len(specs)},
            )
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "CuaDriver 会话占用中",
                f"本机仅允许一个 CUA UI 会话（当前由 {holder} 占用）。Web 用例已尝试 Playwright；其余记为未执行，依赖 Tester 代码审查。",
                severity="warning",
                action_hint="等待其它 iteration 完成或改用 Playwright selector Web spec；native UI 需空闲 CuaDriver。",
                run_id=run_id,
            )
        if result.fallback == "playwright":
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "已切换 Playwright 执行 Web UI 测试",
                result.warning or "Web selector trajectory 或 CuaDriver 不可用场景已由 Playwright 执行。",
                severity="info",
                action_hint="原生 UI 仍需 CuaDriver；查看 UI 验证结果与截图 artifact。",
            )
        if result.warning and not result.fallback:
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "部分 UI 未执行",
                result.warning,
                severity="warning",
                action_hint=f"安装 UI 依赖以执行 Web selector trajectory：{UI_DRIVER_INSTALL_HINT}",
            )
        elif result.warning and any(item.kind == "native" and item.status == "warning" for item in result.results):
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "部分 UI 未执行",
                result.warning,
                severity="warning",
                action_hint=f"原生 UI 需要 CuaDriver：{CUA_INSTALL_HINT}",
            )
        if any(item.status == "failed" for item in result.results):
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "UI 验证需复核",
                "至少一条 UI trajectory 未通过，已作为非阻断警告记录；本轮是否通过由 Tester 代码审查的 P0/P1 结论决定。",
                severity="warning",
                action_hint="查看 UI 验证结果和截图 artifact；交付前建议人工复核失败 UI 场景。",
            )
        elif not any(item.status == "warning" for item in result.results) or result.fallback:
            self._node_event(iteration_id, "node.completed", "ui_driver", "UI 验证完成", f"已完成 {len(result.results)} 条 UI trajectory。", severity="success")
        return result

    def _load_ui_specs(self, docs: IterationDocs) -> list[UITestSpec]:
        ui_root = docs.root / "tests" / "ui"
        if not ui_root.exists():
            return []
        specs: list[UITestSpec] = []
        for path in sorted(ui_root.glob("*.json")):
            content = path.read_text(encoding="utf-8")
            specs.append(validate_ui_spec_content(path.relative_to(docs.root).as_posix(), content))
        return specs

    def _ui_observations(self, ui_result: UIDriverRunResult) -> list[str]:
        observations: list[str] = []
        if ui_result.fallback == "playwright":
            observations.append("Web UI 验证已由 Playwright 执行（CSS selector trajectory 或 CuaDriver 回退）。")
        for result in ui_result.results:
            driver = f" ({result.driver})" if result.driver else ""
            if result.status == "passed":
                observations.append(f"UI 验证通过{driver}: {result.title or result.id}")
            elif result.status == "failed":
                observations.append(f"UI 验证失败{driver}: {result.title or result.id}: {result.error}")
            elif result.status == "warning":
                observations.append(f"UI 未执行{driver}: {result.title or result.id}: {result.error}")
        return observations

    def _coder_artifact(self, state: PipelineState, run_result: CLIResult) -> CoderArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, CoderArtifact)  # type: ignore[return-value]
        return CoderArtifact(changed_paths=["src/app.py"], summary="dry-run source module generated")

    def _tester_artifact(self, state: PipelineState, run_result: CLIResult) -> TesterArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            artifact = parse_json_artifact(raw, TesterArtifact)  # type: ignore[assignment]
            return self._normalize_tester_artifact(artifact)
        if "force tester failure" in state.get("goal", ""):
            return TesterArtifact(
                verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 0\n- Fail: 3\n""",
                passed=False,
                failure_notes="forced tester failure",
                ux_notes=["验证未通过，暂不建议从用户体验角度验收。"],
                delivery_recommendations=["先修复失败测试，再重新进行交付评审。"],
            )
        return TesterArtifact(
            verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 3\n- Fail: 0\n\n## LangGraph\nThe tester node completed and paused for verify approval.\n\n## 用户体验观察\n- dry-run 流程可以从设计审批推进到验证审批，核心状态对用户可见。\n\n## 交付建议\n- 本轮可以交付；后续建议补充真实 CLI 和浏览器级验收。\n""",
            passed=True,
            ux_notes=["核心流程状态清晰，可被人工审批节点接住。"],
            delivery_recommendations=["本轮可以交付；下一步建议补充真实 CLI smoke test。"],
        )

    def _try_tester_artifact(self, state: PipelineState, run_result: CLIResult) -> TesterArtifact | None:
        try:
            return self._tester_artifact(state, run_result)
        except Exception:
            return None

    def _augment_review_fallback_artifact(self, artifact: TesterArtifact, primary_notes: str) -> None:
        compact_notes = self._compact_failure_notes(primary_notes)
        warning = f"主 Tester 自动化未完成，已改用代码审查兜底: {compact_notes}"
        if warning not in artifact.ui_warnings:
            artifact.ui_warnings.append(warning)
        recommendation = "自动化 UI 验证未完整执行；交付前建议在具备 Playwright/CUA 环境时补跑 UI trajectory。"
        if recommendation not in artifact.delivery_recommendations:
            artifact.delivery_recommendations.append(recommendation)

    def _tester_failure_notes(self, *results: CLIResult) -> str:
        notes: list[str] = []
        for index, result in enumerate(results, start=1):
            text = merge_cli_artifact_output(result.stdout, result.stderr)
            label = "primary" if index == 1 else f"fallback {index - 1}"
            if text.strip():
                notes.append(f"{label}: {self._compact_failure_notes(text)}")
            else:
                notes.append(f"{label}: exit code {result.returncode}")
        return "; ".join(notes)

    def _compact_failure_notes(self, text: str, limit: int = 600) -> str:
        compact = " ".join(text.split())
        if not compact:
            return "no diagnostic output"
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."

    def _write_planner_artifact(self, iteration_id: str, docs: IterationDocs, artifact: PlannerArtifact, *, run_id: Optional[str] = None) -> None:
        paths = {
            "system_design": docs.write_text("system_design.md", artifact.system_design),
            "modification_plan": docs.write_text("modification_plan.md", artifact.modification_plan),
            "testing_plan": docs.write_text("testing_plan.md", artifact.testing_plan),
        }
        for name, path in paths.items():
            self._record_document(iteration_id, name, path)
            self._node_event(iteration_id, "artifact.created", NodeName.planner.value, "规划文档已生成", f"{name} 已写入 iteration 文档目录。", severity="success", document=name, run_id=run_id)
        for file in artifact.tests:
            relative = safe_relative_path(file.path)
            if not relative.parts or relative.parts[0] != "tests" or (len(relative.parts) > 1 and relative.parts[1] == "adversarial"):
                raise ValueError(f"planner test path not allowed: {file.path}")
            if len(relative.parts) >= 3 and relative.parts[1] == "ui" and relative.suffix == ".json":
                validate_ui_spec_content(relative.as_posix(), file.content)
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)
            self._node_event(iteration_id, "artifact.created", NodeName.planner.value, "测试文件已生成", relative.as_posix(), severity="success", document=relative.as_posix(), run_id=run_id)
        context_root = docs.root / "context"
        write_jsonl(context_root / "for_coder.jsonl", resolve_coder_manifest(artifact))
        write_jsonl(context_root / "for_tester.jsonl", resolve_tester_manifest(artifact))
        self._record_document(iteration_id, "context/for_coder.jsonl", context_root / "for_coder.jsonl")
        self._record_document(iteration_id, "context/for_tester.jsonl", context_root / "for_tester.jsonl")

    def _ensure_verify_report_markers(self, text: str) -> str:
        result = text if text.strip() else "# Verify Report\n\n"
        if "# " not in result:
            result = f"# Verify Report\n\n{result.lstrip()}"
        if "Pass" not in result:
            if "## Summary" in result:
                suffix = "" if result.endswith("\n") else "\n"
                result = f"{result}{suffix}- Pass: 0\n- Fail: 0\n"
            else:
                result = f"{result.rstrip()}\n\n## Summary\n- Pass: 0\n- Fail: 0\n"
        return result

    def _write_tester_artifact(self, iteration_id: str, docs: IterationDocs, artifact: TesterArtifact, *, run_id: Optional[str] = None) -> None:
        verify_report = self._ensure_verify_report_markers(artifact.verify_report)
        verify = docs.write_text("verify_report.md", verify_report)
        self._record_document(iteration_id, "verify_report", verify)
        self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "验证报告已生成", "verify_report 已写入 iteration 文档目录。", severity="success", document="verify_report", run_id=run_id)
        if artifact.ui_results or artifact.ui_warnings:
            ui_json = docs.write_text(
                "ui_results.json",
                json.dumps(
                    {
                        "warnings": artifact.ui_warnings,
                        "results": [result.model_dump() for result in artifact.ui_results],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self._record_document(iteration_id, "ui_results", ui_json)
            ui_report = docs.write_text("ui_report.md", self._ui_report_markdown(artifact))
            self._record_document(iteration_id, "ui_report", ui_report)
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "UI 验证产物已生成", "ui_results 和 ui_report 已写入 iteration 文档目录。", severity="success", document="ui_report", run_id=run_id)
        advice = self._delivery_advice_markdown(artifact)
        if advice:
            advice_path = docs.write_text("delivery_advice.md", advice)
            self._record_document(iteration_id, "delivery_advice", advice_path)
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "交付建议已生成", "delivery_advice 已写入 iteration 文档目录。", severity="success", document="delivery_advice", run_id=run_id)
            self._add_event(
                iteration_id,
                event_type="tester.delivery_advice",
                payload={"ux_notes": artifact.ux_notes, "delivery_recommendations": artifact.delivery_recommendations},
            )
        for file in artifact.adversarial_tests:
            relative = safe_relative_path(file.path)
            if relative.parts[:2] != ("tests", "adversarial"):
                raise ValueError(f"tester adversarial path not allowed: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "对抗测试已生成", relative.as_posix(), severity="success", document=relative.as_posix(), run_id=run_id)

    def _ui_report_markdown(self, artifact: TesterArtifact) -> str:
        total = len(artifact.ui_results)
        passed = sum(1 for result in artifact.ui_results if result.status == "passed")
        failed = sum(1 for result in artifact.ui_results if result.status == "failed")
        warnings = sum(1 for result in artifact.ui_results if result.status == "warning") + len(artifact.ui_warnings)
        rows = []
        for result in artifact.ui_results:
            error = result.error or ""
            driver = result.driver or "-"
            rows.append(f"| {result.id} | {result.kind} | {result.target} | {driver} | {result.status} | {error} |")
        warning_lines = "\n".join(f"- {warning}" for warning in artifact.ui_warnings) or "- 无"
        return (
            "---\n"
            "doc: ui_report\n"
            "status: draft\n"
            "owner: node3\n"
            "---\n\n"
            "# UI Driver 验证报告\n\n"
            "## 摘要\n"
            f"- UI 测试数量: {total}\n"
            f"- 通过: {passed}\n"
            f"- 失败: {failed}\n"
            f"- 未执行: {warnings}\n\n"
            "## 结果\n"
            "| ID | 类型 | 目标 | Driver | 状态 | 错误 |\n"
            "|---|---|---|---|---|---|\n"
            f"{chr(10).join(rows) if rows else '| - | - | - | - | - | - |'}\n\n"
            "## 未执行 / 回退说明\n"
            f"{warning_lines}\n"
        )

    def _delivery_advice_markdown(self, artifact: TesterArtifact) -> str:
        if not artifact.ux_notes and not artifact.delivery_recommendations:
            return ""
        ux = "\n".join(f"- {item}" for item in artifact.ux_notes) or "- 暂无"
        recommendations = "\n".join(f"- {item}" for item in artifact.delivery_recommendations) or "- 暂无"
        return (
            "---\n"
            "doc: delivery_advice\n"
            "status: draft\n"
            "owner: node3\n"
            "---\n\n"
            "# 交付建议\n\n"
            "## 用户体验观察\n"
            f"{ux}\n\n"
            "## 后续建议\n"
            f"{recommendations}\n"
        )

    def _integrity_problems(self, iteration_id: str) -> list[str]:
        row = self._require_iteration(iteration_id)
        baseline = self._json(row["test_integrity_baseline"], {})
        return compare_test_integrity(self.docs_root(iteration_id), baseline)

    def _normalize_tester_artifact(self, artifact: TesterArtifact) -> TesterArtifact:
        defects = enrich_defects(artifact)
        failure_notes = summarize_failure_notes(artifact) if defects else artifact.failure_notes
        return artifact.model_copy(update={"defects": defects, "failure_notes": failure_notes})

    def _gate_failed_artifact(self, artifact: TesterArtifact, gate_msg: str) -> TesterArtifact:
        defect = Defect(severity="P0", owner="tester", message=gate_msg)
        defects = [*artifact.defects, defect] if artifact.defects else [defect]
        return artifact.model_copy(update={"passed": False, "defects": defects, "failure_notes": gate_msg})

    def _run_artifact_gate(self, state: PipelineState) -> tuple[bool, str]:
        iteration_id = state["iteration_id"]
        row = self._require_iteration(iteration_id)
        test_command = row["test_command"] if "test_command" in row.keys() else None
        build_command = row["build_command"] if "build_command" in row.keys() else None
        if not build_command:
            build_command = self._project_field(state, "default_build_command")
        if not test_command and not build_command:
            return True, ""
        return run_project_commands(
            self.project_repo_root(iteration_id),
            build_command=build_command,
            test_command=test_command,
        )

    def _rollback_tester_adversarial(self, iteration_id: str, adversarial_tests: list[ArtifactFile]) -> None:
        docs_root = self.docs_root(iteration_id)
        for file in adversarial_tests:
            relative = safe_relative_path(file.path)
            path = docs_root / relative
            if path.exists():
                path.unlink()

    def _route_tester_failure(self, state: PipelineState, run_id: str, artifact: TesterArtifact) -> PipelineState:
        iteration_id = state["iteration_id"]
        artifact = self._normalize_tester_artifact(artifact)
        target = retry_target(artifact)
        notes = artifact.failure_notes or summarize_failure_notes(artifact)

        if target == "blocked":
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.tester.value,
                "验证失败涉及受保护测试",
                notes,
                severity="error",
                run_id=run_id,
                action_hint="受保护测试只能由 Planner 修改；需要人工介入。",
            )
            return self._block(iteration_id, "tester.protected_test_failure", run_id, notes)

        if target == "tester":
            retry_counts = self._increment_count(state, "tester_self")
            max_retries = state.get("max_tester_self_retries", 3)
            if retry_counts["tester_self"] > max_retries:
                self._update_iteration(iteration_id, retry_counts=retry_counts)
                return self._block(iteration_id, "tester.self_max_retries", run_id, notes)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.retrying.value,
                current_node=None,
                retry_counts=retry_counts,
                last_error=notes,
            )
            self._add_event(
                iteration_id,
                event_type="tester.retry_to_self",
                payload={"run_id": run_id, "notes": notes, "count": retry_counts["tester_self"], "retry_target": "tester"},
            )
            self._node_event(
                iteration_id,
                "node.progress",
                NodeName.tester.value,
                "验证产物不合格，Tester 自修",
                notes,
                severity="warning",
                run_id=run_id,
                action_hint=f"缺陷落在 Tester 写区，无需 Coder 改 src；第 {retry_counts['tester_self']} 次 Tester 自修。",
            )
            return {
                "route": "self_retry",
                "failure_notes": notes,
                "retry_target": "tester",
                "retry_counts": retry_counts,
                "tester_run_id": run_id,
            }

        retry_counts = self._increment_count(state, "coder_tester")
        if retry_counts["coder_tester"] > state.get("max_coder_tester_retries", 5):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "tester.max_retries", run_id, notes)
        self._update_iteration(
            iteration_id,
            status=IterationStatus.retrying.value,
            current_node=None,
            retry_counts=retry_counts,
            last_error=notes,
        )
        self._add_event(
            iteration_id,
            event_type="tester.retry_to_coder",
            payload={"run_id": run_id, "notes": notes, "count": retry_counts["coder_tester"], "retry_target": "coder"},
        )
        self._node_event(
            iteration_id,
            "node.progress",
            NodeName.tester.value,
            "验证失败，回到实现节点",
            notes,
            severity="warning",
            run_id=run_id,
            action_hint=f"缺陷落在 Coder 写区；第 {retry_counts['coder_tester']} 次实现/验证重试。",
        )
        return {
            "route": "retry",
            "failure_notes": notes,
            "retry_target": "coder",
            "retry_counts": retry_counts,
            "tester_run_id": run_id,
        }

    def _tester_retry_or_block(self, state: PipelineState, run_id: str, notes: str) -> PipelineState:
        artifact = TesterArtifact(
            verify_report="# Verify Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
            passed=False,
            failure_notes=notes,
        )
        return self._route_tester_failure(state, run_id, artifact)

    def _increment_count(self, state: PipelineState, key: str) -> dict[str, int]:
        counts = dict(state.get("retry_counts") or {})
        counts[key] = counts.get(key, 0) + 1
        return counts

    def _json(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _ui_results(self, iteration_id: str) -> list[UITestResult]:
        path = self.docs_root(iteration_id) / "ui_results.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_results = payload.get("results", []) if isinstance(payload, dict) else []
            return [UITestResult.model_validate(item) for item in raw_results]
        except Exception:
            return []

    def _node_event(
        self,
        iteration_id: str,
        event_type: str,
        node: str,
        title: str,
        message: str,
        *,
        severity: str = "info",
        run_id: Optional[str] = None,
        document: Optional[str] = None,
        action_hint: Optional[str] = None,
    ) -> None:
        payload: dict[str, Any] = {
            "node": node,
            "title": title,
            "message": message,
            "severity": severity,
        }
        if run_id:
            payload["run_id"] = run_id
        if document:
            payload["document"] = document
        if action_hint:
            payload["action_hint"] = action_hint
        self._add_event(iteration_id, event_type=event_type, payload=payload)

    def _error_title(self, event_type: str) -> str:
        titles = {
            "artifact.invalid": "Agent 产物格式无效",
            "ui_spec.invalid": "UI 测试规格无效",
            "test_integrity.failed": "测试完整性失败",
            "planner.failed": "规划节点失败",
            "coder.failed": "实现节点失败",
            "tester.max_retries": "验证重试已达上限",
            "clarification.max_retries": "澄清次数已达上限",
            "planner_verify.max_retries": "规格复核失败",
            "job.failed": "后台任务失败",
        }
        return titles.get(event_type, "流水线已阻断")

    def _error_action_hint(self, event_type: str) -> str:
        hints = {
            "artifact.invalid": "查看对应 agent 的原始日志，确认输出是否为合法 JSON artifact。",
            "ui_spec.invalid": "检查 tests/ui/*.json 是否使用 snake_case 动作名，并符合 UITestSpec schema。",
            "test_integrity.failed": "检查受保护测试是否被修改；必要时重新生成规划和测试基线。",
            "planner.failed": "检查 Claude CLI、模型配置和 API 凭据。",
            "coder.failed": "检查 Claude CLI、工作区权限和失败日志。",
            "tester.max_retries": "查看最后一次验证失败说明，必要时人工调整需求或实现。",
            "clarification.max_retries": "补充需求细节或约束后重新启动迭代。",
            "planner_verify.max_retries": "检查验证报告结构，确保包含测试摘要和通过信息。",
            "job.failed": "查看后端日志，确认后台 worker 和 LangGraph checkpoint 状态。",
        }
        return hints.get(event_type, "查看事件流和运行日志，处理阻断后重新创建或重试迭代。")
