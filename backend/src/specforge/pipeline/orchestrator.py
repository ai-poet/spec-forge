from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ..cli_runner import BaseRunner, DryRunRunner, RealCLIRunner
from ..cli_event_presenter import CliEventPresenter
from ..config import settings
from ..db import Database
from ..docs_io import IterationDocs
from ..docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root
from ..events import EventBroker
from ..context_manifest import RUNTIME_NOTES, append_runtime_note
from ..models import IterationStatus, Mode, NodeName

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
        self.dry_runner = DryRunRunner()
        self.real_runner = RealCLIRunner()
        self.cli_presenter = CliEventPresenter()
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
            "queued": NodeName.prd_planner.value,
            "created": NodeName.prd_planner.value,
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
