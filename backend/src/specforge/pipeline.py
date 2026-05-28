from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from .cli_runner import BaseRunner, CLIResult, DryRunRunner, RealCLIRunner
from .config import settings
from .contracts import ArtifactFile, CoderArtifact, PlannerArtifact, TesterArtifact, parse_json_artifact
from .db import Database, iso, utcnow
from .docs_io import IterationDocs, checksum, compare_test_integrity, safe_relative_path, test_integrity_manifest
from .events import EventBroker, EventEnvelope
from .models import IterationStatus, Mode, NodeName


class PipelineState(TypedDict, total=False):
    iteration_id: str
    project_id: Optional[str]
    project_name: str
    goal: str
    mode: str
    status: str
    current_node: Optional[str]
    design_approval: Optional[str]
    verify_approval: Optional[str]
    blocked_reason: Optional[str]
    failure_notes: Optional[str]
    clarification_request: Optional[str]
    retry_counts: dict[str, int]
    max_coder_tester_retries: int
    max_clarifications: int
    max_verify_rejects: int
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
        settings.langgraph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpointer_context = SqliteSaver.from_conn_string(str(settings.langgraph_db_path))
        self._checkpointer = self._checkpointer_context.__enter__()
        self.graph = self._build_graph().compile(checkpointer=self._checkpointer)

    def project_root(self, iteration_id: str) -> Path:
        return settings.projects_dir / iteration_id

    def docs_root(self, iteration_id: str) -> Path:
        return self.project_root(iteration_id) / "docs"

    def start(self, iteration_id: str) -> None:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        retry_counts = self._json(row["retry_counts"], {})
        state: PipelineState = {
            "iteration_id": iteration_id,
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
            "retry_counts": retry_counts,
            "max_coder_tester_retries": int(project["max_coder_tester_retries"]) if project else 5,
            "max_clarifications": int(project["max_clarifications"]) if project else 3,
            "max_verify_rejects": int(project["max_verify_rejects"]) if project else 2,
        }
        self.graph.invoke(state, config=self._config(iteration_id))
        self._publish_snapshot(iteration_id)

    def approve_design(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "design_approval", note or "approved")

    def approve_verify(self, iteration_id: str, note: Optional[str] = None) -> None:
        self.resume(iteration_id, "verify_approval", note or "approved")

    def resume(self, iteration_id: str, expected_checkpoint: str, note: str) -> None:
        state = self.graph.get_state(self._config(iteration_id))
        if expected_checkpoint not in set(state.next):
            raise ValueError(f"iteration is not awaiting {expected_checkpoint}")
        self.graph.invoke(Command(resume=note), config=self._config(iteration_id))
        self._publish_snapshot(iteration_id)

    def can_resume(self, iteration_id: str, expected_checkpoint: str) -> bool:
        state = self.graph.get_state(self._config(iteration_id))
        return expected_checkpoint in set(state.next)

    def stop_iteration(self, iteration_id: str, reason: str = "stopped by user") -> None:
        self._update_iteration(iteration_id, status=IterationStatus.stopped.value, current_node=None, last_error=reason)
        self._add_event(iteration_id, event_type="iteration.stopped", payload={"reason": reason})

    def retry(self, iteration_id: str, note: Optional[str] = None) -> None:
        row = self._require_iteration(iteration_id)
        if row["status"] == IterationStatus.awaiting_design_approval.value:
            self.approve_design(iteration_id, note=note)
        elif row["status"] == IterationStatus.awaiting_verify_approval.value:
            self.approve_verify(iteration_id, note=note)

    def fail_job(self, iteration_id: str, reason: str) -> None:
        self._block(iteration_id, "job.failed", None, reason)

    def dashboard_snapshot(self, iteration_id: str) -> dict[str, Any]:
        row = self._require_iteration(iteration_id)
        graph_state = self.graph.get_state(self._config(iteration_id))
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "epic_id": row["epic_id"],
            "project_name": row["project_name"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
            "retry_counts": self._json(row["retry_counts"], {}),
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "test_command": row["test_command"],
            "graph_next": list(graph_state.next),
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
        }

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(PipelineState)
        builder.add_node("planner", self._planner_node)
        builder.add_node("design_approval", self._design_approval_node)
        builder.add_node("coder", self._coder_node)
        builder.add_node("planner_clarification", self._planner_clarification_node)
        builder.add_node("integrity_check", self._integrity_check_node)
        builder.add_node("tester", self._tester_node)
        builder.add_node("planner_verify", self._planner_verify_node)
        builder.add_node("verify_approval", self._verify_approval_node)
        builder.add_node("done", self._done_node)
        builder.add_edge(START, "planner")
        builder.add_conditional_edges("planner", self._route_after_planner, {"blocked": END, "approval": "design_approval"})
        builder.add_edge("design_approval", "coder")
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
        builder.add_conditional_edges("tester", self._route_after_tester, {"blocked": END, "retry": "coder", "verify": "planner_verify"})
        builder.add_conditional_edges("planner_verify", self._route_after_planner_verify, {"blocked": END, "retry": "coder", "approval": "verify_approval"})
        builder.add_edge("verify_approval", "done")
        builder.add_edge("done", END)
        return builder

    def _planner_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        goal = state["goal"]
        self.project_root(iteration_id).mkdir(parents=True, exist_ok=True)
        self._update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.planner.value, last_error=None)
        self._add_event(iteration_id, event_type="iteration.started", payload={"status": "planning"})
        run_result = self._execute(state, self._planner_command(state))
        run_id = self._record_run(iteration_id, NodeName.planner.value, run_result)
        if run_result.returncode:
            return self._block(iteration_id, "planner.failed", run_id, run_result.stderr)

        try:
            artifact = self._planner_artifact(state, run_result)
            docs = IterationDocs(self.docs_root(iteration_id))
            docs.ensure()
            self._write_planner_artifact(iteration_id, docs, artifact)
            baseline = test_integrity_manifest(docs.root)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.awaiting_design_approval.value,
                current_node=None,
                test_integrity_baseline=baseline,
                last_error=None,
            )
            self._add_event(iteration_id, event_type="planner.completed", payload={"documents": 3 + len(artifact.tests), "run_id": run_id})
            return {"status": IterationStatus.awaiting_design_approval.value, "current_node": None, "planner_run_id": run_id}
        except Exception as exc:
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

    def _design_approval_node(self, state: PipelineState) -> PipelineState:
        answer = interrupt({"checkpoint": "design", "iteration_id": state["iteration_id"]})
        self._add_event(state["iteration_id"], event_type="design.approved", payload={"note": answer})
        return {"design_approval": str(answer), "status": IterationStatus.coding.value}

    def _coder_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        retry_counts = dict(state.get("retry_counts") or {})
        is_retry = retry_counts.get("coder_tester", 0) > 0
        self._update_iteration(
            iteration_id,
            status=IterationStatus.retrying.value if is_retry else IterationStatus.coding.value,
            current_node=NodeName.coder.value,
            retry_counts=retry_counts,
            last_error=None,
        )
        run_result = self._execute(state, self._coder_command(state))
        run_id = self._record_run(iteration_id, NodeName.coder.value, run_result)
        if run_result.returncode:
            return self._block(iteration_id, "coder.failed", run_id, run_result.stderr)

        try:
            artifact = self._coder_artifact(state, run_result)
        except Exception as exc:
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

        if artifact.clarification_request:
            return {"status": "clarification_requested", "clarification_request": artifact.clarification_request, "coder_run_id": run_id}

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
        return {"status": IterationStatus.testing.value, "current_node": NodeName.integrity_check.value, "coder_run_id": run_id}

    def _planner_clarification_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        retry_counts = self._increment_count(state, "coder_planner_clarify")
        if retry_counts["coder_planner_clarify"] > state.get("max_clarifications", 3):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "clarification.max_retries", None, state.get("clarification_request") or "clarification cap reached", blocked_user=True)
        self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=NodeName.planner_clarification.value, retry_counts=retry_counts)
        self._add_event(iteration_id, event_type="clarification.answered", payload={"request": state.get("clarification_request"), "count": retry_counts["coder_planner_clarify"]})
        return {
            "status": IterationStatus.coding.value,
            "failure_notes": f"Planner clarification answer: proceed using the approved spec. Request was: {state.get('clarification_request')}",
            "clarification_request": None,
            "retry_counts": retry_counts,
        }

    def _integrity_check_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.integrity_check.value)
        problems = self._integrity_problems(iteration_id)
        if problems:
            return self._block(iteration_id, "test_integrity.failed", None, "; ".join(problems))
        self._add_event(iteration_id, event_type="test_integrity.passed", payload={"stage": "before_tester"})
        return {"status": IterationStatus.testing.value, "current_node": NodeName.tester.value}

    def _tester_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.tester.value, last_error=None)
        run_result = self._execute(state, self._tester_command(state))
        run_id = self._record_run(iteration_id, NodeName.tester.value, run_result)
        if run_result.returncode:
            return self._tester_retry_or_block(state, run_id, run_result.stderr)

        try:
            artifact = self._tester_artifact(state, run_result)
            problems = self._integrity_problems(iteration_id)
            if problems:
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            docs = IterationDocs(self.docs_root(iteration_id))
            self._write_tester_artifact(iteration_id, docs, artifact)
            if not artifact.passed:
                return self._tester_retry_or_block(state, run_id, artifact.failure_notes or "tester reported failing tests")
            self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
            self._add_event(iteration_id, event_type="tester.completed", payload={"result": "passed", "run_id": run_id})
            return {"status": "tester_passed", "current_node": None, "tester_run_id": run_id}
        except Exception as exc:
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

    def _planner_verify_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.planner_verify.value)
        docs = IterationDocs(self.docs_root(iteration_id))
        try:
            text = docs.read_text("verify_report.md")
            if "# " not in text or "Pass" not in text:
                raise ValueError("verify_report missing required summary markers")
        except Exception as exc:
            retry_counts = self._increment_count(state, "planner_verify_reject")
            if retry_counts["planner_verify_reject"] > state.get("max_verify_rejects", 2):
                self._update_iteration(iteration_id, retry_counts=retry_counts)
                return self._block(iteration_id, "planner_verify.max_retries", None, str(exc))
            self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=NodeName.planner_verify.value, retry_counts=retry_counts, last_error=str(exc))
            self._add_event(iteration_id, event_type="planner_verify.rejected", payload={"reason": str(exc), "count": retry_counts["planner_verify_reject"]})
            return {"status": "verify_rejected", "failure_notes": str(exc), "retry_counts": retry_counts}
        self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
        self._add_event(iteration_id, event_type="planner_verify.accepted", payload={"report": "verify_report"})
        return {"status": IterationStatus.awaiting_verify_approval.value, "current_node": None}

    def _verify_approval_node(self, state: PipelineState) -> PipelineState:
        answer = interrupt({"checkpoint": "verify", "iteration_id": state["iteration_id"]})
        self._add_event(state["iteration_id"], event_type="verify.approved", payload={"note": answer})
        return {"verify_approval": str(answer), "status": IterationStatus.delivered.value}

    def _done_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.delivered.value, current_node=None, last_error=None)
        self._add_event(iteration_id, event_type="iteration.delivered", payload={"status": "delivered"})
        return {"status": IterationStatus.delivered.value, "current_node": None}

    def _route_after_planner(self, state: PipelineState) -> Literal["blocked", "approval"]:
        return "blocked" if state.get("status") == IterationStatus.blocked.value else "approval"

    def _route_after_coder(self, state: PipelineState) -> Literal["blocked", "clarification", "integrity"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value}:
            return "blocked"
        if state.get("status") == "clarification_requested":
            return "clarification"
        return "integrity"

    def _route_after_clarification(self, state: PipelineState) -> Literal["blocked", "coder"]:
        return "blocked" if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value} else "coder"

    def _route_after_integrity(self, state: PipelineState) -> Literal["blocked", "tester"]:
        return "blocked" if state.get("status") == IterationStatus.blocked.value else "tester"

    def _route_after_tester(self, state: PipelineState) -> Literal["blocked", "retry", "verify"]:
        if state.get("status") == IterationStatus.blocked.value:
            return "blocked"
        if state.get("status") == "tester_failed_retry":
            return "retry"
        return "verify"

    def _route_after_planner_verify(self, state: PipelineState) -> Literal["blocked", "retry", "approval"]:
        if state.get("status") == IterationStatus.blocked.value:
            return "blocked"
        if state.get("status") == "verify_rejected":
            return "retry"
        return "approval"

    def _config(self, iteration_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": iteration_id}}

    def _require_iteration(self, iteration_id: str):
        row = self.db.get_iteration_row(iteration_id)
        if row is None:
            raise KeyError(iteration_id)
        return row

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
        return {"status": status, "current_node": None, "blocked_reason": reason}

    def _execute(self, state: PipelineState, command: list[str]) -> CLIResult:
        runner = self.real_runner if self._is_real_cli(state.get("mode")) else self.dry_runner
        return runner.run(command, cwd=self.project_root(state["iteration_id"]))

    def _is_real_cli(self, mode: Optional[str]) -> bool:
        return mode == Mode.real_cli.value or settings.mode == Mode.real_cli.value

    def _planner_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = (
                "You are Planner for SpecForge. Return only JSON matching this shape: "
                "{system_design:string, modification_plan:string, testing_plan:string, "
                "tests:[{path:string, content:string}]}. "
                "Use test paths under tests/unit, tests/integration, or tests/ui. "
                f"Goal: {state['goal']}"
            )
            command = ["claude", "-p", "--output-format", "json", "--permission-mode", "plan", prompt]
            model = self._project_field(state, "planner_model")
            if model:
                command[1:1] = ["--model", model]
            return command
        return ["specforge", "planner", iteration_id]

    def _coder_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            notes = state.get("failure_notes") or ""
            prompt = (
                "You are Coder for SpecForge. Edit only src/** in this iteration workspace. "
                "Do not edit docs/tests. Return only JSON matching "
                "{changed_paths:[string], summary:string, clarification_request?:string}. "
                f"Failure notes to address: {notes}"
            )
            command = ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits", prompt]
            model = self._project_field(state, "coder_model")
            if model:
                command[1:1] = ["--model", model]
            return command
        return ["specforge", "coder", iteration_id]

    def _tester_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = (
                "You are Tester for SpecForge. Run verification. Return only final JSON matching "
                "{verify_report:string, passed:boolean, failure_notes?:string, "
                "adversarial_tests:[{path:string, content:string}]}. "
                "Only propose adversarial tests under tests/adversarial."
            )
            command = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", prompt]
            model = self._project_field(state, "tester_model")
            if model:
                command[2:2] = ["--model", model]
            return command
        return ["specforge", "tester", iteration_id]

    def _project_field(self, state: PipelineState, field: str) -> Optional[str]:
        project_id = state.get("project_id")
        if not project_id:
            return None
        project = self.db.get_project_row(project_id)
        if project is None:
            return None
        return project[field]

    def _planner_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerArtifact:
        if self._is_real_cli(state.get("mode")):
            return parse_json_artifact(run_result.stdout, PlannerArtifact)  # type: ignore[return-value]
        goal = state["goal"]
        return PlannerArtifact(
            system_design=f"""---\ndoc: system_design\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - System Design\n\nGoal: {goal}\n\nThis dry-run design was produced by the LangGraph planner node.\n""",
            modification_plan="""---\ndoc: modification_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Modification Plan\n\n- Generate a minimal source module.\n- Preserve planner-authored tests.\n- Hand off implementation to the coder node after approval.\n""",
            testing_plan="""---\ndoc: testing_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Testing Plan\n\n- T01: backend health endpoint responds.\n- T02: dry-run reaches verify approval.\n- T03: delivered status requires verify approval.\n""",
            tests=[
                ArtifactFile(
                    path="tests/unit/test_transitions.py",
                    content="from specforge.models import IterationStatus\n\n\ndef test_status_names_exist():\n    assert IterationStatus.created.value == 'created'\n",
                )
            ],
        )

    def _coder_artifact(self, state: PipelineState, run_result: CLIResult) -> CoderArtifact:
        if self._is_real_cli(state.get("mode")):
            return parse_json_artifact(run_result.stdout, CoderArtifact)  # type: ignore[return-value]
        return CoderArtifact(changed_paths=["src/app.py"], summary="dry-run source module generated")

    def _tester_artifact(self, state: PipelineState, run_result: CLIResult) -> TesterArtifact:
        if self._is_real_cli(state.get("mode")):
            return parse_json_artifact(run_result.stdout, TesterArtifact)  # type: ignore[return-value]
        if "force tester failure" in state.get("goal", ""):
            return TesterArtifact(
                verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 0\n- Fail: 3\n""",
                passed=False,
                failure_notes="forced tester failure",
            )
        return TesterArtifact(
            verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 3\n- Fail: 0\n\n## LangGraph\nThe tester node completed and paused for verify approval.\n""",
            passed=True,
        )

    def _write_planner_artifact(self, iteration_id: str, docs: IterationDocs, artifact: PlannerArtifact) -> None:
        paths = {
            "system_design": docs.write_text("system_design.md", artifact.system_design),
            "modification_plan": docs.write_text("modification_plan.md", artifact.modification_plan),
            "testing_plan": docs.write_text("testing_plan.md", artifact.testing_plan),
        }
        for name, path in paths.items():
            self._record_document(iteration_id, name, path)
        for file in artifact.tests:
            relative = safe_relative_path(file.path)
            if not relative.parts or relative.parts[0] != "tests" or (len(relative.parts) > 1 and relative.parts[1] == "adversarial"):
                raise ValueError(f"planner test path not allowed: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)

    def _write_tester_artifact(self, iteration_id: str, docs: IterationDocs, artifact: TesterArtifact) -> None:
        verify = docs.write_text("verify_report.md", artifact.verify_report)
        self._record_document(iteration_id, "verify_report", verify)
        for file in artifact.adversarial_tests:
            relative = safe_relative_path(file.path)
            if relative.parts[:2] != ("tests", "adversarial"):
                raise ValueError(f"tester adversarial path not allowed: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)

    def _integrity_problems(self, iteration_id: str) -> list[str]:
        row = self._require_iteration(iteration_id)
        baseline = self._json(row["test_integrity_baseline"], {})
        return compare_test_integrity(self.docs_root(iteration_id), baseline)

    def _tester_retry_or_block(self, state: PipelineState, run_id: str, notes: str) -> PipelineState:
        iteration_id = state["iteration_id"]
        retry_counts = self._increment_count(state, "coder_tester")
        if retry_counts["coder_tester"] > state.get("max_coder_tester_retries", 5):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "tester.max_retries", run_id, notes)
        self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=None, retry_counts=retry_counts, last_error=notes)
        self._add_event(iteration_id, event_type="tester.failed_retry", payload={"run_id": run_id, "notes": notes, "count": retry_counts["coder_tester"]})
        return {"status": "tester_failed_retry", "failure_notes": notes, "retry_counts": retry_counts, "tester_run_id": run_id}

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
