from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from typing_extensions import TypedDict

from .cli_runner import BaseRunner, CLIResult, DryRunRunner, RealCLIRunner
from .config import settings
from .contracts import (
    ArtifactFile,
    CoderArtifact,
    PlannerArtifact,
    TesterArtifact,
    UIDriverRunResult,
    UITestResult,
    UITestSpec,
    parse_json_artifact,
)
from .db import Database, iso, utcnow
from .docs_io import IterationDocs, checksum, compare_test_integrity, safe_relative_path, test_integrity_manifest
from .events import EventBroker, EventEnvelope
from .models import IterationStatus, Mode, NodeName
from .ui_driver import UIDriverRunner


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
        self.ui_driver = UIDriverRunner()
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
            "ui_results": [result.model_dump() for result in self._ui_results(iteration_id)],
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
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.planner.value,
            "规划节点已启动",
            "正在读取需求并准备生成系统设计、修改计划和测试。",
        )
        self._add_event(iteration_id, event_type="iteration.started", payload={"status": "planning"})
        run_result = self._execute(state, self._planner_command(state))
        run_id = self._record_run(iteration_id, NodeName.planner.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.planner.value, "规划失败", "Planner CLI 执行失败。", severity="error", run_id=run_id, action_hint="查看运行日志，确认 claude CLI 可用并能返回 JSON artifact。")
            return self._block(iteration_id, "planner.failed", run_id, run_result.stderr)

        try:
            self._node_event(iteration_id, "node.progress", NodeName.planner.value, "正在解析规划产物", "已收到 Planner 输出，正在校验 JSON artifact 并写入文档。", run_id=run_id)
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
            self._node_event(iteration_id, "node.completed", NodeName.planner.value, "规划完成", f"已生成 3 份规划文档和 {len(artifact.tests)} 个测试文件，等待设计审批。", severity="success", run_id=run_id)
            return {"status": IterationStatus.awaiting_design_approval.value, "current_node": None, "planner_run_id": run_id}
        except Exception as exc:
            self._node_event(iteration_id, "node.failed", NodeName.planner.value, "规划产物无效", "Planner 输出无法被解析为合法 artifact。", severity="error", run_id=run_id, action_hint="查看 Planner 原始日志，要求模型只输出符合 schema 的 JSON。")
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
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.coder.value,
            "实现节点已启动" if not is_retry else "实现节点正在重试",
            "Coder 正在根据批准后的规格修改代码。" if not is_retry else "Coder 正在根据上一轮失败信息修复实现。",
        )
        run_result = self._execute(state, self._coder_command(state))
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
        self._node_event(iteration_id, "node.completed", NodeName.coder.value, "实现完成", artifact.summary or "代码实现已完成，准备进入测试完整性检查。", severity="success", run_id=run_id)
        return {"status": IterationStatus.testing.value, "current_node": NodeName.integrity_check.value, "coder_run_id": run_id}

    def _planner_clarification_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        retry_counts = self._increment_count(state, "coder_planner_clarify")
        if retry_counts["coder_planner_clarify"] > state.get("max_clarifications", 3):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "clarification.max_retries", None, state.get("clarification_request") or "clarification cap reached", blocked_user=True)
        self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=NodeName.planner_clarification.value, retry_counts=retry_counts)
        self._node_event(iteration_id, "node.progress", NodeName.planner_clarification.value, "Planner 已处理澄清", "系统将带着澄清结果回到实现节点。", severity="info", action_hint="无需人工处理，系统会继续回环。")
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
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.tester.value, last_error=None)
        self._node_event(iteration_id, "node.started", NodeName.tester.value, "验证节点已启动", "Tester 正在独立运行验证并准备交付建议。")
        run_result = self._execute(state, self._tester_command(state))
        run_id = self._record_run(iteration_id, NodeName.tester.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证命令失败", "Tester CLI 执行失败，系统将尝试回到实现节点修复。", severity="error", run_id=run_id, action_hint="查看 Tester 原始日志和失败信息。")
            return self._tester_retry_or_block(state, run_id, run_result.stderr)

        try:
            self._node_event(iteration_id, "node.progress", NodeName.tester.value, "正在解析验证结果", "已收到 Tester 输出，正在校验验证报告、交付建议和对抗测试。", run_id=run_id)
            artifact = self._tester_artifact(state, run_result)
            problems = self._integrity_problems(iteration_id)
            if problems:
                self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证前测试完整性失败", "; ".join(problems), severity="error", run_id=run_id, action_hint="检查测试目录是否被实现节点修改。")
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            docs = IterationDocs(self.docs_root(iteration_id))
            ui_result = self._run_ui_specs(iteration_id, docs)
            if ui_result.results:
                artifact.ui_results.extend(ui_result.results)
                artifact.ux_notes.extend(self._ui_observations(ui_result))
            if ui_result.warning:
                artifact.ui_warnings.append(ui_result.warning)
                artifact.delivery_recommendations.append(f"UI Driver 未完整执行: {ui_result.warning}")
                self._add_event(iteration_id, event_type="ui_driver.warning", payload={"warning": ui_result.warning})
            elif ui_result.results:
                self._add_event(iteration_id, event_type="ui_driver.completed", payload={"count": len(ui_result.results)})
            if any(result.status == "failed" for result in ui_result.results):
                artifact.passed = False
                artifact.failure_notes = artifact.failure_notes or "UI verification failed"
                self._add_event(
                    iteration_id,
                    event_type="ui_driver.failed",
                    payload={"failed": [result.model_dump() for result in ui_result.results if result.status == "failed"]},
                )
            self._write_tester_artifact(iteration_id, docs, artifact)
            problems = self._integrity_problems(iteration_id)
            if problems:
                self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证后测试完整性失败", "; ".join(problems), severity="error", run_id=run_id, action_hint="Tester 只能写入 adversarial 和 UI recordings；请检查异常测试文件。")
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            if not artifact.passed:
                self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证未通过", artifact.failure_notes or "测试失败，系统将尝试回到实现节点。", severity="error", run_id=run_id, action_hint="查看失败说明，等待自动重试或处理阻断。")
                return self._tester_retry_or_block(state, run_id, artifact.failure_notes or "tester reported failing tests")
            self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
            self._add_event(iteration_id, event_type="tester.completed", payload={"result": "passed", "run_id": run_id})
            self._node_event(iteration_id, "node.completed", NodeName.tester.value, "验证通过", "验证报告和交付建议已生成，等待规格复核和最终确认。", severity="success", run_id=run_id)
            return {"status": "tester_passed", "current_node": None, "tester_run_id": run_id}
        except Exception as exc:
            self._node_event(iteration_id, "node.failed", NodeName.tester.value, "验证产物无效", "Tester 输出无法被解析为合法 artifact。", severity="error", run_id=run_id, action_hint="查看 Tester 原始日志，要求模型只输出符合 schema 的 JSON。")
            return self._block(iteration_id, "artifact.invalid", run_id, str(exc))

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
            return {"status": "verify_rejected", "failure_notes": str(exc), "retry_counts": retry_counts}
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
        self._update_iteration(iteration_id, status=IterationStatus.delivered.value, current_node=None, last_error=None)
        self._add_event(iteration_id, event_type="iteration.delivered", payload={"status": "delivered"})
        self._node_event(iteration_id, "node.completed", "done", "迭代已交付", "本轮流水线已完成并归档为已交付状态。", severity="success")
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
        return {"status": status, "current_node": None, "blocked_reason": reason}

    def _execute(self, state: PipelineState, command: list[str]) -> CLIResult:
        runner = self.real_runner if self._is_real_cli(state.get("mode")) else self.dry_runner
        iteration_id = state["iteration_id"]
        current_node = state.get("current_node") or "agent"
        seen_output = {"stdout": False, "stderr": False}
        seen_cli_events: set[str] = set()

        def on_output(stream: str, chunk: str) -> None:
            if not chunk.strip():
                return
            if stream == "stdout" and self._is_real_cli(state.get("mode")):
                for event in self._native_cli_events(chunk):
                    key = event.get("key")
                    if key and key in seen_cli_events:
                        continue
                    if key:
                        seen_cli_events.add(key)
                    self._node_event(
                        iteration_id,
                        "node.progress",
                        str(current_node),
                        event["title"],
                        event["message"],
                        severity=event["severity"],
                    )
                if seen_cli_events:
                    return
            if seen_output[stream]:
                return
            seen_output[stream] = True
            self._node_event(
                iteration_id,
                "node.progress",
                str(current_node),
                "已收到模型输出" if stream == "stdout" else "已收到错误输出",
                "Agent CLI 正在输出内容，原始日志已保存到运行记录。" if stream == "stdout" else "Agent CLI 输出了错误流，必要时请展开原始日志排查。",
                severity="info" if stream == "stdout" else "warning",
            )

        return runner.run(command, cwd=self.project_root(iteration_id), on_output=on_output)

    def _native_cli_events(self, chunk: str) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        for line in [line.strip() for line in chunk.splitlines() if line.strip()]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = self._present_native_cli_event(payload)
            if event:
                events.append(event)
        return events

    def _present_native_cli_event(self, payload: dict[str, Any]) -> Optional[dict[str, str]]:
        msg = payload.get("msg") if isinstance(payload.get("msg"), dict) else {}
        event_type = str(payload.get("type") or payload.get("event") or msg.get("type") or "")
        item = payload.get("item") if isinstance(payload.get("item"), dict) else msg.get("item") if isinstance(msg.get("item"), dict) else {}
        item_type = str(item.get("type") or "")
        subtype = str(payload.get("subtype") or "")
        if event_type == "system" and subtype == "init":
            return {"key": "claude.init", "title": "Claude Code 会话已初始化", "message": "CLI 已完成会话启动，正在准备工具和上下文。", "severity": "info"}
        if event_type == "assistant":
            return {"key": "claude.assistant", "title": "Claude 正在生成方案", "message": "模型正在输出规划或实现内容，最终 artifact 会由后端解析。", "severity": "info"}
        if event_type == "result":
            return {"key": "claude.result", "title": "Claude 输出已完成", "message": "CLI 已返回最终结果，正在进入 artifact 校验。", "severity": "success"}
        if event_type == "thread.started":
            return {"key": "codex.thread.started", "title": "Codex 验证会话已启动", "message": "Tester 已创建独立执行线程，准备运行验证。", "severity": "info"}
        if event_type == "turn.started":
            return {"key": "codex.turn.started", "title": "Codex 回合已开始", "message": "Tester 正在分析任务、执行命令或准备验证报告。", "severity": "info"}
        if event_type == "turn.completed":
            return {"key": "codex.turn.completed", "title": "Codex 回合已完成", "message": "Tester 已完成本轮验证输出，正在解析报告。", "severity": "success"}
        if event_type == "turn.failed":
            return {"key": "codex.turn.failed", "title": "Codex 回合失败", "message": "Tester 执行过程中出现失败，详情保存在原始日志。", "severity": "error"}
        if event_type == "item.started":
            return {"key": f"codex.item.started.{item_type}", "title": self._codex_item_title(item_type, started=True), "message": self._codex_item_message(item, started=True), "severity": "info"}
        if event_type == "item.completed":
            return {"key": f"codex.item.completed.{item_type}", "title": self._codex_item_title(item_type, started=False), "message": self._codex_item_message(item, started=False), "severity": "success" if item_type != "command_execution" else "info"}
        if event_type == "agent_reasoning":
            return {"key": "codex.agent_reasoning", "title": "Codex 正在推理", "message": str(payload.get("text") or "Tester 正在形成验证判断。"), "severity": "info"}
        if event_type == "agent_message":
            return {"key": "codex.agent_message", "title": "Codex 已生成验证说明", "message": "Tester 正在输出最终报告内容。", "severity": "info"}
        return None

    def _codex_item_title(self, item_type: str, *, started: bool) -> str:
        action = "开始" if started else "完成"
        labels = {
            "reasoning": "推理",
            "agent_reasoning": "推理",
            "agent_message": "报告输出",
            "command_execution": "命令执行",
            "tool_call": "工具调用",
        }
        return f"Codex {labels.get(item_type, item_type or '步骤')}{action}"

    def _codex_item_message(self, item: dict[str, Any], *, started: bool) -> str:
        command = item.get("command") or item.get("cmd")
        if isinstance(command, list):
            command_text = " ".join(map(str, command))
            return f"{'正在执行' if started else '已执行'}命令: {command_text}"
        text = item.get("text") or item.get("summary")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return "原始 CLI 事件已保存，可以在日志中展开查看。"

    def _is_real_cli(self, mode: Optional[str]) -> bool:
        return mode == Mode.real_cli.value or settings.mode == Mode.real_cli.value

    def _planner_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = (
                "You are Planner for SpecForge. Return only JSON matching this shape: "
                "{system_design:string, modification_plan:string, testing_plan:string, "
                "tests:[{path:string, content:string}]}. "
                "Use code test paths under tests/unit or tests/integration. "
                "For UI tests, write JSON specs under tests/ui/*.json with shape "
                "{id,title,kind:web|native,target:{url|bundle_id|app_name},steps:[{action,text,value,key,keys,direction,amount}]}. "
                f"Goal: {state['goal']}"
            )
            command = [
                "claude",
                "-p",
                "--output-format",
                "stream-json",
                "--input-format",
                "text",
                "--permission-mode",
                "plan",
                "--verbose",
                "--include-partial-messages",
                "--json-schema",
                self._artifact_schema_inline(PlannerArtifact),
                prompt,
            ]
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
            command = [
                "claude",
                "-p",
                "--output-format",
                "stream-json",
                "--input-format",
                "text",
                "--permission-mode",
                "acceptEdits",
                "--verbose",
                "--include-partial-messages",
                "--json-schema",
                self._artifact_schema_inline(CoderArtifact),
                prompt,
            ]
            model = self._project_field(state, "coder_model")
            if model:
                command[1:1] = ["--model", model]
            return command
        return ["specforge", "coder", iteration_id]

    def _tester_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = (
                "You are Tester and independent delivery reviewer for SpecForge. Run verification, inspect user-facing behavior where possible, "
                "and include practical post-delivery recommendations. Return only final JSON matching "
                "{verify_report:string, passed:boolean, failure_notes?:string, "
                "ux_notes:[string], delivery_recommendations:[string], "
                "ui_results?:[], ui_warnings?:[], adversarial_tests:[{path:string, content:string}]}. "
                "Only propose adversarial tests under tests/adversarial."
            )
            command = [
                "codex",
                "exec",
                "--json",
                "--output-schema",
                str(self._artifact_schema_file(iteration_id, "tester_artifact", TesterArtifact)),
                "--sandbox",
                "workspace-write",
                "--skip-git-repo-check",
                prompt,
            ]
            model = self._project_field(state, "tester_model")
            if model:
                command[2:2] = ["--model", model]
            return command
        return ["specforge", "tester", iteration_id]

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

    def _run_ui_specs(self, iteration_id: str, docs: IterationDocs) -> UIDriverRunResult:
        specs = self._load_ui_specs(docs)
        if not specs:
            return UIDriverRunResult(available=True, results=[])
        self._node_event(iteration_id, "node.started", "ui_driver", "UI Driver 已启动", f"正在执行 {len(specs)} 条 UI trajectory。")
        self._add_event(iteration_id, event_type="ui_driver.started", payload={"count": len(specs)})
        result = self.ui_driver.run_specs(specs, docs.root)
        if result.warning:
            self._node_event(
                iteration_id,
                "node.progress",
                "ui_driver",
                "UI Driver 已降级",
                result.warning,
                severity="warning",
                action_hint="Cua 不可用或权限不足，本轮不会因此阻断交付。",
            )
        elif any(item.status == "failed" for item in result.results):
            self._node_event(
                iteration_id,
                "node.failed",
                "ui_driver",
                "UI 验证失败",
                "至少一条 UI trajectory 未通过，系统将进入实现/验证重试。",
                severity="error",
                action_hint="查看 UI 验证结果和截图 artifact。",
            )
        else:
            self._node_event(iteration_id, "node.completed", "ui_driver", "UI 验证完成", f"已完成 {len(result.results)} 条 UI trajectory。", severity="success")
        return result

    def _load_ui_specs(self, docs: IterationDocs) -> list[UITestSpec]:
        ui_root = docs.root / "tests" / "ui"
        if not ui_root.exists():
            return []
        specs: list[UITestSpec] = []
        for path in sorted(ui_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            specs.append(UITestSpec.model_validate(payload))
        return specs

    def _ui_observations(self, ui_result: UIDriverRunResult) -> list[str]:
        observations: list[str] = []
        for result in ui_result.results:
            if result.status == "passed":
                observations.append(f"UI 验证通过: {result.title or result.id}")
            elif result.status == "failed":
                observations.append(f"UI 验证失败: {result.title or result.id}: {result.error}")
            elif result.status == "warning":
                observations.append(f"UI 验证降级: {result.title or result.id}: {result.error}")
        return observations

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
                ux_notes=["验证未通过，暂不建议从用户体验角度验收。"],
                delivery_recommendations=["先修复失败测试，再重新进行交付评审。"],
            )
        return TesterArtifact(
            verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 3\n- Fail: 0\n\n## LangGraph\nThe tester node completed and paused for verify approval.\n\n## 用户体验观察\n- dry-run 流程可以从设计审批推进到验证审批，核心状态对用户可见。\n\n## 交付建议\n- 本轮可以交付；后续建议补充真实 CLI 和浏览器级验收。\n""",
            passed=True,
            ux_notes=["核心流程状态清晰，可被人工审批节点接住。"],
            delivery_recommendations=["本轮可以交付；下一步建议补充真实 CLI smoke test。"],
        )

    def _write_planner_artifact(self, iteration_id: str, docs: IterationDocs, artifact: PlannerArtifact) -> None:
        paths = {
            "system_design": docs.write_text("system_design.md", artifact.system_design),
            "modification_plan": docs.write_text("modification_plan.md", artifact.modification_plan),
            "testing_plan": docs.write_text("testing_plan.md", artifact.testing_plan),
        }
        for name, path in paths.items():
            self._record_document(iteration_id, name, path)
            self._node_event(iteration_id, "artifact.created", NodeName.planner.value, "规划文档已生成", f"{name} 已写入 iteration 文档目录。", severity="success", document=name)
        for file in artifact.tests:
            relative = safe_relative_path(file.path)
            if not relative.parts or relative.parts[0] != "tests" or (len(relative.parts) > 1 and relative.parts[1] == "adversarial"):
                raise ValueError(f"planner test path not allowed: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)
            self._node_event(iteration_id, "artifact.created", NodeName.planner.value, "测试文件已生成", relative.as_posix(), severity="success", document=relative.as_posix())

    def _write_tester_artifact(self, iteration_id: str, docs: IterationDocs, artifact: TesterArtifact) -> None:
        verify = docs.write_text("verify_report.md", artifact.verify_report)
        self._record_document(iteration_id, "verify_report", verify)
        self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "验证报告已生成", "verify_report 已写入 iteration 文档目录。", severity="success", document="verify_report")
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
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "UI 验证产物已生成", "ui_results 和 ui_report 已写入 iteration 文档目录。", severity="success", document="ui_report")
        advice = self._delivery_advice_markdown(artifact)
        if advice:
            advice_path = docs.write_text("delivery_advice.md", advice)
            self._record_document(iteration_id, "delivery_advice", advice_path)
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "交付建议已生成", "delivery_advice 已写入 iteration 文档目录。", severity="success", document="delivery_advice")
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
            self._node_event(iteration_id, "artifact.created", NodeName.tester.value, "对抗测试已生成", relative.as_posix(), severity="success", document=relative.as_posix())

    def _ui_report_markdown(self, artifact: TesterArtifact) -> str:
        total = len(artifact.ui_results)
        passed = sum(1 for result in artifact.ui_results if result.status == "passed")
        failed = sum(1 for result in artifact.ui_results if result.status == "failed")
        warnings = sum(1 for result in artifact.ui_results if result.status == "warning") + len(artifact.ui_warnings)
        rows = []
        for result in artifact.ui_results:
            error = result.error or ""
            rows.append(f"| {result.id} | {result.kind} | {result.target} | {result.status} | {error} |")
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
            f"- Warning: {warnings}\n\n"
            "## 结果\n"
            "| ID | 类型 | 目标 | 状态 | 错误 |\n"
            "|---|---|---|---|---|\n"
            f"{chr(10).join(rows) if rows else '| - | - | - | - | - |'}\n\n"
            "## 降级信息\n"
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

    def _tester_retry_or_block(self, state: PipelineState, run_id: str, notes: str) -> PipelineState:
        iteration_id = state["iteration_id"]
        retry_counts = self._increment_count(state, "coder_tester")
        if retry_counts["coder_tester"] > state.get("max_coder_tester_retries", 5):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "tester.max_retries", run_id, notes)
        self._update_iteration(iteration_id, status=IterationStatus.retrying.value, current_node=None, retry_counts=retry_counts, last_error=notes)
        self._add_event(iteration_id, event_type="tester.failed_retry", payload={"run_id": run_id, "notes": notes, "count": retry_counts["coder_tester"]})
        self._node_event(
            iteration_id,
            "node.progress",
            NodeName.tester.value,
            "验证失败，准备自动重试",
            notes,
            severity="warning",
            run_id=run_id,
            action_hint=f"系统将回到实现节点修复，这是第 {retry_counts['coder_tester']} 次实现/验证重试。",
        )
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
            "test_integrity.failed": "检查受保护测试是否被修改；必要时重新生成规划和测试基线。",
            "planner.failed": "检查 Claude CLI、模型配置和 API 凭据。",
            "coder.failed": "检查 Claude CLI、工作区权限和失败日志。",
            "tester.max_retries": "查看最后一次验证失败说明，必要时人工调整需求或实现。",
            "clarification.max_retries": "补充需求细节或约束后重新启动迭代。",
            "planner_verify.max_retries": "检查验证报告结构，确保包含测试摘要和通过信息。",
            "job.failed": "查看后端日志，确认后台 worker 和 LangGraph checkpoint 状态。",
        }
        return hints.get(event_type, "查看事件流和运行日志，处理阻断后重新创建或重试迭代。")
