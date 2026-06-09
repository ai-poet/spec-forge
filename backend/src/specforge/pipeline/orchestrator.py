from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ..agents.codex_sdk_runner import CodexSdkRunner
from ..agents.cli_runner import BaseRunner, DryRunRunner, RealCLIRunner
from ..agents.cli_event_presenter import CliEventPresenter
from ..core.config import settings
from ..core.contracts import (
    ContextManifestEntry,
    PrdPlannerArtifact,
    TestPlannerArtifact,
    VerificationArtifact,
)
from ..core.models import IterationStatus, Mode, NodeName
from ..documents.docs_io import IterationDocs, planning_integrity_manifest, test_integrity_manifest
from ..documents.docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root
from ..policy.context_manifest import RUNTIME_NOTES, append_runtime_note
from ..runtime.events import EventBroker
from ..storage.db import Database

from .graph import PipelineGraphMixin
from .mixins.artifacts import PipelineArtifactsMixin
from .mixins.prompts import PipelinePromptsMixin
from .mixins.runtime import PipelineRuntimeMixin
from .mixins.ui_tester import PipelineUiTesterMixin
from .nodes.implementation import ImplementationNodesMixin
from .nodes.planning import PlanningNodesMixin
from .nodes.verification import VerificationNodesMixin
from .routes import PipelineRoutesMixin
from .state import PipelineState


MANUAL_SKIP_NEXT_NODE: dict[str, str] = {
    NodeName.planner_discovery.value: NodeName.prd_planner.value,
    "requirements_input": NodeName.prd_planner.value,
    NodeName.prd_planner.value: NodeName.test_planner.value,
    NodeName.test_planner.value: NodeName.coder.value,
    NodeName.planner_clarification.value: NodeName.coder.value,
    NodeName.coder.value: NodeName.code_tester.value,
    NodeName.code_tester.value: NodeName.integrity_check.value,
    NodeName.integrity_check.value: NodeName.ui_tester.value,
    NodeName.ui_tester.value: NodeName.planner_verify.value,
    NodeName.planner_verify.value: "verify_approval",
    "verify_approval": "done",
}

MANUAL_SKIP_ACTIVE_STATUSES = {
    IterationStatus.created.value,
    IterationStatus.queued.value,
    IterationStatus.planning.value,
    IterationStatus.awaiting_requirements_input.value,
    IterationStatus.coding.value,
    IterationStatus.retrying.value,
    IterationStatus.testing.value,
}

TERMINAL_JOB_STATUSES = {
    IterationStatus.delivered.value,
    IterationStatus.blocked.value,
    IterationStatus.blocked_user.value,
    IterationStatus.failed.value,
    IterationStatus.stopped.value,
}

DB_STATE_REFRESH_KEYS = {
    "iteration_id",
    "project_id",
    "project_name",
    "goal",
    "epic_title",
    "epic_description",
    "epic_acceptance_criteria",
    "mode",
    "max_coder_tester_retries",
    "max_tester_self_retries",
    "max_clarifications",
    "max_verify_rejects",
    "max_discovery_rounds",
    "planning_cli_session_id",
    "planning_cli_session_started",
}

TERMINAL_RECOVERY_STATUSES = {
    IterationStatus.delivered.value,
    IterationStatus.blocked.value,
    IterationStatus.blocked_user.value,
    IterationStatus.failed.value,
}

ACTIVE_RUNTIME_STATUSES = {
    IterationStatus.planning.value,
    IterationStatus.coding.value,
    IterationStatus.retrying.value,
    IterationStatus.testing.value,
}

START_RECOVERY_STATUSES = {
    IterationStatus.created.value,
    IterationStatus.queued.value,
}

AUTO_RESUME_STATUSES = ACTIVE_RUNTIME_STATUSES | {IterationStatus.stopped.value}

MANUAL_WAIT_NODES = {
    "requirements_input",
    "verify_approval",
}

AUTO_RESUMABLE_NODES = {
    NodeName.planner_discovery.value,
    NodeName.prd_planner.value,
    NodeName.test_planner.value,
    NodeName.planner_clarification.value,
    NodeName.coder.value,
    NodeName.code_tester.value,
    NodeName.integrity_check.value,
    NodeName.ui_tester.value,
    NodeName.planner_verify.value,
}


class LangGraphPipeline(
    PlanningNodesMixin,
    ImplementationNodesMixin,
    VerificationNodesMixin,
    PipelineUiTesterMixin,
    PipelineArtifactsMixin,
    PipelinePromptsMixin,
    PipelineRoutesMixin,
    PipelineGraphMixin,
    PipelineRuntimeMixin,
):

    def __init__(self, db: Database, runner: BaseRunner, broker: Optional[EventBroker] = None) -> None:
        self.db = db
        self.runner = runner
        self.broker = broker or EventBroker()
        self.dry_runner = runner if isinstance(runner, DryRunRunner) else DryRunRunner()
        self.real_runner = runner if isinstance(runner, RealCLIRunner) else RealCLIRunner(registry_path=settings.active_cli_registry_path)
        self.codex_runner = CodexSdkRunner()
        self.cli_presenter = CliEventPresenter()
        settings.langgraph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpointer_context = SqliteSaver.from_conn_string(str(settings.langgraph_db_path))
        self._checkpointer = self._checkpointer_context.__enter__()
        self.graph = self._build_graph().compile(checkpointer=self._checkpointer)
        self._live_cli_lock = Lock()
        self._live_cli: dict[str, dict[str, str]] = {}
        self._live_cli_last_publish: dict[str, float] = {}
        self._live_cli_chunk_last_publish: dict[str, float] = {}
        self._live_cli_pending_chunks: dict[tuple[str, str], dict[str, str]] = {}
        self._aborted_iterations: set[str] = set()
        self._invoking: set[str] = set()
        self._checkpointer_closed = False


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
        self._ensure_graph_open()
        self._begin_invoke(iteration_id)
        try:
            state = self._build_state(iteration_id)
            self.graph.invoke(state, config=self._config(iteration_id))
        finally:
            self._end_invoke(iteration_id)
        self._publish_snapshot(iteration_id)


    def can_start_job(self, iteration_id: str) -> bool:
        row = self.db.get_iteration_row(iteration_id)
        return row is not None and row["status"] in {IterationStatus.created.value, IterationStatus.queued.value}


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
            "planning_cli_session_id": row["planning_cli_session_id"] if "planning_cli_session_id" in row.keys() else None,
            "planning_cli_session_started": bool(row["planning_cli_session_started"]) if "planning_cli_session_started" in row.keys() else False,
        }


    def _checkpoint_state_with_db_refresh(self, iteration_id: str) -> PipelineState:
        self._ensure_graph_open()
        db_state = self._build_state(iteration_id)
        graph_state = self.graph.get_state(self._config(iteration_id))
        if not graph_state.values:
            return db_state
        state = dict(graph_state.values)
        for key in DB_STATE_REFRESH_KEYS:
            if key in db_state:
                state[key] = db_state[key]
        return state


    def answer_requirements(self, iteration_id: str, answer: str) -> None:
        self.resume(iteration_id, "requirements_input", answer)


    def skip_discovery(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "requirements_input", f"SKIP:{note or 'proceed with documented assumptions'}")


    def approve_verify(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "verify_approval", note or "approved")


    def prepare_manual_skip(self, iteration_id: str, node: Optional[str] = None, note: Optional[str] = None) -> str:
        row = self._require_iteration(iteration_id)
        if row["status"] == IterationStatus.delivered.value:
            raise ValueError("delivered iteration cannot be skipped")
        skip_node = self._resolve_manual_skip_node(row, node)
        next_node = self._manual_skip_next(skip_node)
        if row["status"] in MANUAL_SKIP_ACTIVE_STATUSES:
            self.cancel_cli(iteration_id)
        else:
            self._clear_live_cli(iteration_id)
        self._update_iteration(
            iteration_id,
            status=IterationStatus.stopped.value,
            current_node=None,
            stopped_at_node=skip_node,
            last_error=f"manual skip queued: {skip_node}",
        )
        self._add_event(
            iteration_id,
            event_type="manual_skip.queued",
            payload={"node": skip_node, "next_node": next_node, "note": note},
        )
        return skip_node


    def manual_skip(self, iteration_id: str, node: str, note: Optional[str] = None) -> None:
        self._ensure_graph_open()
        skip_node = self._normalize_manual_skip_node(node)
        next_node = self._manual_skip_next(skip_node)
        self._aborted_iterations.discard(iteration_id)
        self._clear_live_cli(iteration_id)
        state_updates = self._ensure_manual_skip_prerequisites(iteration_id, skip_node, next_node, note)
        status = IterationStatus.delivered if next_node == "done" else self._status_for_node(next_node)
        current_node = None if next_node in {"verify_approval", "done"} else next_node
        self._update_iteration(
            iteration_id,
            status=status.value,
            current_node=current_node,
            stopped_at_node=None,
            last_error=None,
        )
        self._add_event(
            iteration_id,
            event_type="manual_skip.started",
            payload={"node": skip_node, "next_node": next_node, "note": note},
        )
        self._node_event(
            iteration_id,
            "node.completed",
            skip_node,
            "人工跳过",
            note or "该环节已由人工调试操作跳过。",
            severity="warning",
            action_hint="这是调试操作，产物可能由系统生成的最小占位内容补齐。",
        )

        state = self._checkpoint_state_with_db_refresh(iteration_id)
        state.update(
            {
                "status": status.value,
                "current_node": current_node,
                "route": "",
                "blocked_reason": None,
                **state_updates,
            }
        )
        if self._manual_skip_order(next_node) < self._manual_skip_order(NodeName.integrity_check.value):
            state["pending_code_tester_json"] = None
            state["code_tester_run_id"] = None
        self.graph.update_state(self._config(iteration_id), state)
        self._begin_invoke(iteration_id)
        try:
            self.graph.invoke(Command(goto=next_node), config=self._config(iteration_id))
        finally:
            self._end_invoke(iteration_id)
        self._publish_snapshot(iteration_id)


    def _resolve_manual_skip_node(self, row: Any, node: Optional[str]) -> str:
        if node:
            return self._normalize_manual_skip_node(node)
        if row["status"] == IterationStatus.awaiting_requirements_input.value:
            return "requirements_input"
        if row["status"] == IterationStatus.awaiting_verify_approval.value:
            return "verify_approval"
        if row["current_node"]:
            return self._normalize_manual_skip_node(row["current_node"])
        if "stopped_at_node" in row.keys() and row["stopped_at_node"]:
            return self._normalize_manual_skip_node(row["stopped_at_node"])
        inferred = self._infer_node_from_status(row["status"])
        if inferred:
            return self._normalize_manual_skip_node(inferred)
        event_node = self._last_event_node(row["id"])
        if event_node:
            return event_node
        raise ValueError("cannot determine node to skip")


    def _normalize_manual_skip_node(self, node: str) -> str:
        aliases = {
            "coder_retry": NodeName.coder.value,
            "ui_driver": NodeName.ui_tester.value,
        }
        normalized = aliases.get(node, node)
        if normalized not in MANUAL_SKIP_NEXT_NODE:
            raise ValueError(f"node cannot be manually skipped: {node}")
        return normalized


    def _manual_skip_next(self, node: str) -> str:
        try:
            return MANUAL_SKIP_NEXT_NODE[node]
        except KeyError as exc:
            raise ValueError(f"node cannot be manually skipped: {node}") from exc


    def _last_event_node(self, iteration_id: str) -> Optional[str]:
        runs = {run["id"]: run["node"] for run in self.db.list_runs(iteration_id)}
        for event in reversed(self.db.list_events(iteration_id)):
            try:
                payload = json.loads(event["payload"])
            except Exception:
                continue
            node = payload.get("node")
            if isinstance(node, str) and node in MANUAL_SKIP_NEXT_NODE:
                return node
            run_id = payload.get("run_id")
            run_node = runs.get(run_id) if isinstance(run_id, str) else None
            if run_node in MANUAL_SKIP_NEXT_NODE:
                return run_node
        return None


    def _manual_skip_order(self, node: str) -> int:
        order = {
            NodeName.prd_planner.value: 1,
            NodeName.test_planner.value: 2,
            NodeName.coder.value: 3,
            NodeName.code_tester.value: 4,
            NodeName.integrity_check.value: 5,
            NodeName.ui_tester.value: 6,
            NodeName.planner_verify.value: 7,
            "verify_approval": 8,
            "done": 9,
        }
        return order.get(node, 0)


    def _ensure_manual_skip_prerequisites(
        self,
        iteration_id: str,
        skip_node: str,
        next_node: str,
        note: Optional[str],
    ) -> dict[str, Any]:
        self._prepare_iteration_docs(iteration_id)
        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        state_updates: dict[str, Any] = {
            "requirements_brief": self._manual_requirements_brief(iteration_id, note),
            "failure_notes": note or f"manual skip from {skip_node}",
        }
        if self._manual_skip_order(next_node) >= self._manual_skip_order(NodeName.test_planner.value):
            self._ensure_manual_prd(iteration_id, docs, note)
        if self._manual_skip_order(next_node) >= self._manual_skip_order(NodeName.coder.value):
            self._ensure_manual_testing_plan(iteration_id, docs, note)
            self._update_iteration(iteration_id, planning_integrity_baseline=planning_integrity_manifest(docs.root))
        if self._manual_skip_order(next_node) >= self._manual_skip_order(NodeName.integrity_check.value):
            artifact = self._ensure_manual_verification(iteration_id, docs, skip_node, note)
            state_updates["pending_code_tester_json"] = artifact.model_dump_json()
            state_updates["code_tester_run_id"] = None
        return state_updates


    def _manual_requirements_brief(self, iteration_id: str, note: Optional[str]) -> str:
        row = self._require_iteration(iteration_id)
        brief = f"Goal: {row['goal']}\n\nManual skip note: {note or 'debug skip'}"
        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        path = docs.write_text(
            "discovery/requirements_brief.md",
            f"---\ndoc: discovery\nstatus: manual\nowner: user\n---\n\n# Requirements Brief\n\n{brief}\n",
        )
        self._record_document(iteration_id, "requirements_brief", path)
        return brief


    def _ensure_manual_prd(self, iteration_id: str, docs: IterationDocs, note: Optional[str]) -> None:
        prd_path = docs.root / "prd.md"
        coder_context = docs.root / "context" / "for_coder.jsonl"
        tester_context = docs.root / "context" / "for_tester.jsonl"
        if prd_path.exists() and coder_context.exists() and tester_context.exists():
            return
        row = self._require_iteration(iteration_id)
        prd = prd_path.read_text(encoding="utf-8") if prd_path.exists() else (
            "---\ndoc: prd\nstatus: manual\nowner: user\n---\n\n"
            "# Manual PRD Placeholder\n\n"
            f"Goal: {row['goal']}\n\n"
            f"Manual skip note: {note or 'debug skip'}\n\n"
            "## Acceptance Criteria\n- Continue pipeline debugging with manually supplied assumptions.\n"
        )
        artifact = PrdPlannerArtifact(
            prd=prd,
            context_for_coder=[ContextManifestEntry(file="prd.md", reason="Manual skip PRD placeholder")],
            context_for_tester=[ContextManifestEntry(file="prd.md", reason="Manual skip PRD placeholder")],
        )
        self._write_prd_planner_artifact(iteration_id, docs, artifact)


    def _ensure_manual_testing_plan(self, iteration_id: str, docs: IterationDocs, note: Optional[str]) -> None:
        plan_path = docs.root / "testing_plan.md"
        if not plan_path.exists():
            artifact = TestPlannerArtifact(
                testing_plan=(
                    "---\ndoc: testing_plan\nstatus: manual\nowner: user\n---\n\n"
                    "# Manual Testing Plan Placeholder\n\n"
                    "## Automated Tests\n- Skipped by manual debug control.\n\n"
                    "## Manual Tests\n- Continue to the next pipeline stage for debugging.\n\n"
                    f"Note: {note or 'debug skip'}\n"
                )
            )
            self._write_test_planner_artifact(iteration_id, docs, artifact)


    def _ensure_manual_verification(
        self,
        iteration_id: str,
        docs: IterationDocs,
        skip_node: str,
        note: Optional[str],
    ) -> VerificationArtifact:
        report_path = docs.root / "verify_report.md"
        report = report_path.read_text(encoding="utf-8") if report_path.exists() else (
            "---\ndoc: verify_report\nstatus: manual\nowner: user\n---\n\n"
            "# Manual Verify Report Placeholder\n\n"
            "## Summary\n- Tests executed: 0\n- Pass: 0\n- Fail: 0\n\n"
            f"Manually skipped `{skip_node}` for pipeline debugging.\n"
        )
        artifact = VerificationArtifact(
            verify_report=report,
            passed=True,
            ux_notes=[f"Manual skip from {skip_node}: {note or 'debug skip'}"],
            delivery_recommendations=["Manual skip was used; rerun the skipped agent before treating this as production evidence."],
        )
        self._write_tester_artifact(iteration_id, docs, artifact)
        self._update_iteration(iteration_id, test_integrity_baseline=test_integrity_manifest(docs.root))
        return artifact


    def resume(self, iteration_id: str, expected_checkpoint: str, note: str) -> None:
        self._ensure_graph_open()
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
        self._ensure_graph_open()
        state = self.graph.get_state(self._config(iteration_id))
        return expected_checkpoint in set(state.next)


    def cancel_cli(self, iteration_id: str) -> None:
        self._aborted_iterations.add(iteration_id)
        self.real_runner.cancel(iteration_id)
        self.codex_runner.cancel(iteration_id)
        self._clear_live_cli(iteration_id)


    def shutdown(self) -> list[str]:
        cancelled = [*self.real_runner.cancel_all(), *self.codex_runner.cancel_all()]
        for iteration_id in cancelled:
            self._clear_live_cli(iteration_id)
            self.stop_iteration(iteration_id, "service shutting down")
        self._stop_active_runtime_iterations("service shutting down")
        self.close_checkpointer()
        return cancelled


    def close_checkpointer(self) -> None:
        if self._checkpointer_closed:
            return
        self._checkpointer_closed = True
        self._checkpointer_context.__exit__(None, None, None)


    def _ensure_graph_open(self) -> None:
        if not self._checkpointer_closed:
            return
        settings.langgraph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpointer_context = SqliteSaver.from_conn_string(str(settings.langgraph_db_path))
        self._checkpointer = self._checkpointer_context.__enter__()
        self.graph = self._build_graph().compile(checkpointer=self._checkpointer)
        self._checkpointer_closed = False


    def forget_iteration_state(self, iteration_id: str) -> None:
        self._ensure_graph_open()
        try:
            self._checkpointer.delete_thread(iteration_id)
        except Exception:
            pass


    def resync_runtime_state(self) -> list[str]:
        cleaned = [*self.real_runner.cleanup_registry_processes(), *self.codex_runner.cleanup_registry_processes()]
        for iteration_id in cleaned:
            self._clear_live_cli(iteration_id)
            self._mark_runtime_stopped(iteration_id, "service restarted while CLI was running")
        self._stop_active_runtime_iterations("service restarted; CLI state was not active")
        return cleaned


    def _stop_active_runtime_iterations(self, reason: str) -> None:
        for row in self.db.list_iterations():
            if row["status"] in ACTIVE_RUNTIME_STATUSES:
                self._mark_runtime_stopped(row["id"], reason)


    def recover_interrupted_iterations(self, job_queue: Any) -> list[dict[str, Any]]:
        self.resync_runtime_state()
        decisions: list[dict[str, Any]] = []
        for row in self.db.list_iterations():
            decision = self._recovery_decision(row)
            if decision["category"] == "terminal":
                continue
            iteration_id = row["id"]
            queued = False
            if decision["action"] == "start":
                queued = bool(job_queue.enqueue_start(iteration_id))
            elif decision["action"] == "resume_stopped":
                queued = bool(job_queue.enqueue_resume_stopped(iteration_id, "automatic recovery after service restart"))

            if decision["action"]:
                payload = {
                    "category": decision["category"],
                    "action": decision["action"],
                    "node": decision["node"],
                    "reason": decision["reason"] if queued else "already_pending",
                }
                self._add_event(
                    iteration_id,
                    event_type="runtime.auto_resume_queued" if queued else "runtime.auto_resume_skipped",
                    payload=payload,
                )
                decisions.append({**payload, "iteration_id": iteration_id, "queued": queued})
            elif decision["category"] in {"manual_waiting", "skipped"}:
                payload = {
                    "category": decision["category"],
                    "node": decision["node"],
                    "reason": decision["reason"],
                }
                self._add_event(iteration_id, event_type="runtime.auto_resume_skipped", payload=payload)
                decisions.append({**payload, "iteration_id": iteration_id, "queued": False})
        return decisions


    def recovery_category(self, row: Any) -> Literal["auto_resumable", "manual_waiting", "terminal", "skipped"]:
        return self._recovery_decision(row)["category"]  # type: ignore[return-value]


    def _recovery_decision(self, row: Any) -> dict[str, Any]:
        status = row["status"]
        node = self._stopped_resume_node(row)
        if status in TERMINAL_RECOVERY_STATUSES:
            return {"category": "terminal", "action": None, "node": node, "reason": "terminal_status"}
        if status in {
            IterationStatus.awaiting_requirements_input.value,
            IterationStatus.awaiting_verify_approval.value,
        } or node in MANUAL_WAIT_NODES:
            return {"category": "manual_waiting", "action": None, "node": node, "reason": "manual_waiting"}
        if status in START_RECOVERY_STATUSES:
            if self._checkpoint_has_values(row["id"]):
                return {"category": "skipped", "action": None, "node": node, "reason": "checkpoint_exists"}
            return {
                "category": "auto_resumable",
                "action": "start",
                "node": NodeName.planner_discovery.value,
                "reason": "queued_without_checkpoint",
            }
        if status not in AUTO_RESUME_STATUSES:
            return {"category": "skipped", "action": None, "node": node, "reason": f"status_not_recoverable:{status}"}
        if not node:
            return {"category": "skipped", "action": None, "node": None, "reason": "missing_resume_node"}
        if node not in AUTO_RESUMABLE_NODES:
            return {"category": "skipped", "action": None, "node": node, "reason": "node_not_auto_resumable"}
        return {"category": "auto_resumable", "action": "resume_stopped", "node": node, "reason": "interrupted_runtime"}


    def _checkpoint_has_values(self, iteration_id: str) -> bool:
        self._ensure_graph_open()
        try:
            return bool(self.graph.get_state(self._config(iteration_id)).values)
        except Exception:
            return False


    def _mark_runtime_stopped(self, iteration_id: str, reason: str) -> None:
        row = self.db.get_iteration_row(iteration_id)
        if row is None or row["status"] in {"delivered", "blocked", "blocked_user", "failed", "stopped"}:
            return
        stopped_at_node = self._stopped_resume_node(row)
        self._aborted_iterations.add(iteration_id)
        self._update_iteration(
            iteration_id,
            status=IterationStatus.stopped.value,
            current_node=None,
            stopped_at_node=stopped_at_node,
            last_error=reason,
        )
        self._add_event(
            iteration_id,
            event_type="runtime.resynced",
            payload={"reason": reason, "node": stopped_at_node},
        )


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
        self._ensure_graph_open()
        row = self._require_iteration(iteration_id)
        if row["status"] != IterationStatus.stopped.value:
            raise ValueError("iteration is not stopped")
        resume_node = self._stopped_resume_node(row)
        if not resume_node:
            raise ValueError("cannot determine resume step")
        resume_note = (note or "").strip()

        self._aborted_iterations.discard(iteration_id)
        config = self._config(iteration_id)
        if resume_note:
            self.add_runtime_note(iteration_id, resume_note, node=resume_node)

        if resume_node == "requirements_input" and self.can_resume(iteration_id, "requirements_input"):
            self.resume(iteration_id, "requirements_input", resume_note or "resumed")
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
                payload={"node": resume_node, "note": resume_note or None},
            )
            self._begin_invoke(iteration_id)
            try:
                self.graph.invoke(Command(resume=resume_note or "resumed"), config=config)
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
            payload={"node": resume_node, "note": resume_note or None},
        )

        state = self._checkpoint_state_with_db_refresh(iteration_id)
        if resume_note:
            state["failure_notes"] = resume_note
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
            "queued": NodeName.planner_discovery.value,
            "created": NodeName.planner_discovery.value,
            "planning": NodeName.planner_discovery.value,
            "awaiting_requirements_input": "requirements_input",
            "coding": NodeName.coder.value,
            "retrying": NodeName.coder.value,
            "testing": NodeName.code_tester.value,
            "awaiting_verify_approval": "verify_approval",
        }.get(status)


    def _status_for_node(self, node: str) -> IterationStatus:
        mapping = {
            NodeName.planner_discovery.value: IterationStatus.planning,
            NodeName.prd_planner.value: IterationStatus.planning,
            NodeName.test_planner.value: IterationStatus.planning,
            NodeName.planner_clarification.value: IterationStatus.retrying,
            "requirements_input": IterationStatus.awaiting_requirements_input,
            NodeName.coder.value: IterationStatus.coding,
            NodeName.integrity_check.value: IterationStatus.testing,
            NodeName.code_tester.value: IterationStatus.testing,
            NodeName.ui_tester.value: IterationStatus.testing,
            NodeName.planner_verify.value: IterationStatus.testing,
            "verify_approval": IterationStatus.awaiting_verify_approval,
            "done": IterationStatus.delivered,
        }
        return mapping.get(node, IterationStatus.queued)


    def retry(self, iteration_id: str, note: Optional[str] = None) -> None:
        row = self._require_iteration(iteration_id)
        if row["status"] == IterationStatus.awaiting_verify_approval.value:
            self.approve_verify(iteration_id, note=note)


    def fail_job(self, iteration_id: str, reason: str) -> None:
        row = self.db.get_iteration_row(iteration_id)
        if row is None or row["status"] in TERMINAL_JOB_STATUSES:
            if row is not None:
                self._add_event(iteration_id, event_type="job.failed_ignored", payload={"reason": reason, "status": row["status"]})
            return
        self._block(iteration_id, "job.failed", None, reason)


    def dashboard_snapshot(self, iteration_id: str) -> dict[str, Any]:
        self._ensure_graph_open()
        detail_rows = self.db.iteration_detail_rows(iteration_id)
        if detail_rows is None:
            raise KeyError(iteration_id)
        row = detail_rows["iteration"]
        documents = detail_rows["documents"]
        events = detail_rows["events"]
        runs = detail_rows["runs"]
        graph_state = None
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
            "last_error": self._truncate_public_text(row["last_error"], self._PUBLIC_EVENT_TEXT_MAX_CHARS) if row["last_error"] else None,
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
                for doc in documents
            ],
            "events": self._public_event_records(events[-self._PUBLIC_EVENT_LIMIT :]),
            "runs": [
                self._public_run_record(iteration_id, run)
                for run in runs[-self._PUBLIC_RUN_LIMIT :]
            ],
            "ui_results": [result.model_dump() for result in self._ui_results(iteration_id)],
            "live_cli": self._live_cli_snapshot(iteration_id),
            **self._discovery_snapshot_fields(iteration_id, graph_state=graph_state, skip_graph=iteration_id in self._invoking),
        }


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
