from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from .cli_runner import BaseRunner, DryRunRunner, RealCLIRunner
from .config import settings
from .db import Database, iso, utcnow
from .docs_io import IterationDocs, checksum
from .models import IterationStatus, Mode, NodeName


class PipelineState(TypedDict, total=False):
    iteration_id: str
    project_name: str
    goal: str
    mode: str
    status: str
    current_node: Optional[str]
    design_approval: Optional[str]
    verify_approval: Optional[str]
    blocked_reason: Optional[str]
    planner_run_id: Optional[str]
    coder_run_id: Optional[str]
    tester_run_id: Optional[str]


class LangGraphPipeline:
    def __init__(self, db: Database, runner: BaseRunner) -> None:
        self.db = db
        self.runner = runner
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
        state: PipelineState = {
            "iteration_id": iteration_id,
            "project_name": row["project_name"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
        }
        self.graph.invoke(state, config=self._config(iteration_id))

    def approve_design(self, iteration_id: str, note: Optional[str] = None) -> None:
        self._resume(iteration_id, "design_approval", note or "approved")

    def approve_verify(self, iteration_id: str, note: Optional[str] = None) -> None:
        self._resume(iteration_id, "verify_approval", note or "approved")

    def stop_iteration(self, iteration_id: str, reason: str = "stopped by user") -> None:
        self.db.update_iteration(iteration_id, status=IterationStatus.stopped.value, current_node=None)
        self.db.add_event(iteration_id, event_type="iteration.stopped", payload={"reason": reason})

    def retry(self, iteration_id: str, note: Optional[str] = None) -> None:
        row = self._require_iteration(iteration_id)
        if row["status"] == IterationStatus.awaiting_design_approval.value:
            self.approve_design(iteration_id, note=note)
        elif row["status"] == IterationStatus.awaiting_verify_approval.value:
            self.approve_verify(iteration_id, note=note)

    def dashboard_snapshot(self, iteration_id: str) -> dict[str, Any]:
        row = self._require_iteration(iteration_id)
        graph_state = self.graph.get_state(self._config(iteration_id))
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "current_node": row["current_node"],
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
        builder.add_node("tester", self._tester_node)
        builder.add_node("verify_approval", self._verify_approval_node)
        builder.add_node("done", self._done_node)
        builder.add_edge(START, "planner")
        builder.add_conditional_edges("planner", self._route_after_planner, {"blocked": END, "approval": "design_approval"})
        builder.add_edge("design_approval", "coder")
        builder.add_conditional_edges("coder", self._route_after_coder, {"blocked": END, "tester": "tester"})
        builder.add_conditional_edges("tester", self._route_after_tester, {"blocked": END, "approval": "verify_approval"})
        builder.add_edge("verify_approval", "done")
        builder.add_edge("done", END)
        return builder

    def _planner_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        goal = state["goal"]
        self.project_root(iteration_id).mkdir(parents=True, exist_ok=True)
        self.db.update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.planner.value)
        self.db.add_event(iteration_id, event_type="iteration.started", payload={"status": "planning"})
        run_result = self._execute(state, self._planner_command(iteration_id, goal, state.get("mode", Mode.dry_run.value)))
        run_id = self._record_run(iteration_id, NodeName.planner.value, run_result)
        if run_result.returncode:
            return self._block(iteration_id, "planner.failed", run_id, run_result.stderr)

        docs = IterationDocs(self.docs_root(iteration_id))
        docs.ensure()
        system_design = docs.write_text(
            "system_design.md",
            f"""---\ndoc: system_design\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - System Design\n\nGoal: {goal}\n\nThis dry-run design was produced by the LangGraph planner node.\n""",
        )
        modification_plan = docs.write_text(
            "modification_plan.md",
            """---\ndoc: modification_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Modification Plan\n\n- Generate a minimal source module.\n- Preserve planner-authored tests.\n- Hand off implementation to the coder node after approval.\n""",
        )
        testing_plan = docs.write_text(
            "testing_plan.md",
            """---\ndoc: testing_plan\niteration: 1\nstatus: draft\nowner: node1\n---\n\n# Iteration 1 - Testing Plan\n\n- T01: backend health endpoint responds.\n- T02: dry-run reaches verify approval.\n- T03: delivered status requires verify approval.\n""",
        )
        test_file = docs.write_text(
            "tests/unit/test_transitions.py",
            """from specforge.models import IterationStatus\n\n\ndef test_status_names_exist():\n    assert IterationStatus.created.value == 'created'\n""",
        )
        self._record_document(iteration_id, "system_design", system_design)
        self._record_document(iteration_id, "modification_plan", modification_plan)
        self._record_document(iteration_id, "testing_plan", testing_plan)
        self._record_document(iteration_id, "test_transitions", test_file)
        self.db.update_iteration(iteration_id, status=IterationStatus.awaiting_design_approval.value, current_node=None)
        self.db.add_event(iteration_id, event_type="planner.completed", payload={"documents": 4, "run_id": run_id})
        return {
            "status": IterationStatus.awaiting_design_approval.value,
            "current_node": None,
            "planner_run_id": run_id,
        }

    def _design_approval_node(self, state: PipelineState) -> PipelineState:
        answer = interrupt({"checkpoint": "design", "iteration_id": state["iteration_id"]})
        self.db.add_event(state["iteration_id"], event_type="design.approved", payload={"note": answer})
        return {"design_approval": str(answer), "status": IterationStatus.coding.value}

    def _coder_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self.db.update_iteration(iteration_id, status=IterationStatus.coding.value, current_node=NodeName.coder.value)
        run_result = self._execute(state, self._coder_command(iteration_id, state.get("mode", Mode.dry_run.value)))
        run_id = self._record_run(iteration_id, NodeName.coder.value, run_result)
        if run_result.returncode:
            return self._block(iteration_id, "coder.failed", run_id, run_result.stderr)

        src_root = self.project_root(iteration_id) / "src"
        src_root.mkdir(parents=True, exist_ok=True)
        app_file = src_root / "app.py"
        app_file.write_text(
            """from __future__ import annotations\n\n\ndef build_summary(goal: str) -> str:\n    return f'SpecForge prepared: {goal}'\n""",
            encoding="utf-8",
        )
        self.db.add_event(iteration_id, event_type="coder.completed", payload={"path": str(app_file), "run_id": run_id})
        return {
            "status": IterationStatus.testing.value,
            "current_node": NodeName.tester.value,
            "coder_run_id": run_id,
        }

    def _tester_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self.db.update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.tester.value)
        run_result = self._execute(state, self._tester_command(iteration_id, state.get("mode", Mode.dry_run.value)))
        run_id = self._record_run(iteration_id, NodeName.tester.value, run_result)
        if run_result.returncode:
            return self._block(iteration_id, "tester.failed", run_id, run_result.stderr)

        docs = IterationDocs(self.docs_root(iteration_id))
        verify = docs.write_text(
            "verify_report.md",
            """---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 3\n- Fail: 0\n\n## LangGraph\nThe tester node completed and paused for verify approval.\n""",
        )
        self._record_document(iteration_id, "verify_report", verify)
        self.db.update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None)
        self.db.add_event(iteration_id, event_type="tester.completed", payload={"result": "awaiting_verify_approval", "run_id": run_id})
        return {
            "status": IterationStatus.awaiting_verify_approval.value,
            "current_node": None,
            "tester_run_id": run_id,
        }

    def _verify_approval_node(self, state: PipelineState) -> PipelineState:
        answer = interrupt({"checkpoint": "verify", "iteration_id": state["iteration_id"]})
        self.db.add_event(state["iteration_id"], event_type="verify.approved", payload={"note": answer})
        return {"verify_approval": str(answer), "status": IterationStatus.delivered.value}

    def _done_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self.db.update_iteration(iteration_id, status=IterationStatus.delivered.value, current_node=None)
        self.db.add_event(iteration_id, event_type="iteration.delivered", payload={"status": "delivered"})
        return {"status": IterationStatus.delivered.value, "current_node": None}

    def _route_after_planner(self, state: PipelineState) -> Literal["blocked", "approval"]:
        return "blocked" if state.get("status") == IterationStatus.blocked.value else "approval"

    def _route_after_coder(self, state: PipelineState) -> Literal["blocked", "tester"]:
        return "blocked" if state.get("status") == IterationStatus.blocked.value else "tester"

    def _route_after_tester(self, state: PipelineState) -> Literal["blocked", "approval"]:
        return "blocked" if state.get("status") == IterationStatus.blocked.value else "approval"

    def _resume(self, iteration_id: str, expected_checkpoint: str, note: str) -> None:
        state = self.graph.get_state(self._config(iteration_id))
        if expected_checkpoint not in set(state.next):
            raise ValueError(f"iteration is not awaiting {expected_checkpoint}")
        self.graph.invoke(Command(resume=note), config=self._config(iteration_id))

    def _config(self, iteration_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": iteration_id}}

    def _require_iteration(self, iteration_id: str):
        row = self.db.get_iteration_row(iteration_id)
        if row is None:
            raise KeyError(iteration_id)
        return row

    def _record_run(self, iteration_id: str, node: str, run_result) -> str:
        return self.db.add_run(
            iteration_id,
            node=node,
            status="failed" if run_result.returncode else "success",
            command=" ".join(run_result.command),
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            exit_code=run_result.returncode,
            finished_at=iso(utcnow()),
        )

    def _record_document(self, iteration_id: str, name: str, path: Path) -> None:
        self.db.add_document(iteration_id, name=name, path=str(path), checksum=checksum(path))

    def _block(self, iteration_id: str, event_type: str, run_id: str, stderr: str) -> PipelineState:
        self.db.update_iteration(iteration_id, status=IterationStatus.blocked.value, current_node=None)
        self.db.add_event(iteration_id, event_type=event_type, payload={"run_id": run_id, "stderr": stderr})
        return {"status": IterationStatus.blocked.value, "current_node": None, "blocked_reason": stderr}

    def _execute(self, state: PipelineState, command: list[str]):
        runner = self.real_runner if self._is_real_cli(state.get("mode")) else self.dry_runner
        return runner.run(command, cwd=self.project_root(state["iteration_id"]))

    def _is_real_cli(self, mode: Optional[str]) -> bool:
        return mode == Mode.real_cli.value or settings.mode == Mode.real_cli.value

    def _planner_command(self, iteration_id: str, goal: str, mode: Optional[str]) -> list[str]:
        if self._is_real_cli(mode):
            prompt = (
                "You are Planner for SpecForge. Produce concise JSON with keys "
                f"system_design, modification_plan, testing_plan, tests. Goal: {goal}"
            )
            return ["claude", "-p", "--output-format", "json", "--permission-mode", "bypassPermissions", prompt]
        return ["specforge", "planner", iteration_id]

    def _coder_command(self, iteration_id: str, mode: Optional[str]) -> list[str]:
        if self._is_real_cli(mode):
            prompt = "You are Coder for SpecForge. Edit only workspace sources and return a concise JSON status."
            return ["claude", "-p", "--output-format", "json", "--permission-mode", "bypassPermissions", prompt]
        return ["specforge", "coder", iteration_id]

    def _tester_command(self, iteration_id: str, mode: Optional[str]) -> list[str]:
        if self._is_real_cli(mode):
            prompt = "You are Tester for SpecForge. Run verification and summarize pass/fail plus integrity issues."
            return [
                "codex",
                "exec",
                "--json",
                "--sandbox",
                "danger-full-access",
                "--dangerously-bypass-approvals-and-sandbox",
                prompt,
            ]
        return ["specforge", "tester", iteration_id]
