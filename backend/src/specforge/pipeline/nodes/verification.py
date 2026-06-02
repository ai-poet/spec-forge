from __future__ import annotations

from langgraph.types import interrupt

from ...core.contracts import (
    CodeTesterArtifact,
    VerificationArtifact,
    verification_from_code,
    ui_spec_error_type,
)
from ...core.models import IterationStatus, NodeName
from ...documents.docs_io import IterationDocs, test_integrity_manifest
from ...documents.docs_scaffold import append_iteration_log
from ...policy.write_zones import summarize_failure_notes
from ..state import PipelineState


class VerificationNodesMixin:

    def _code_tester_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.code_tester.value, last_error=None)
        self._reset_live_cli(iteration_id, NodeName.code_tester.value)
        self._publish_snapshot(iteration_id)
        self._node_event(iteration_id, "node.started", NodeName.code_tester.value, "代码验证已启动", "Code Tester 正在独立运行代码审查与测试命令。")
        run_result = self._execute(state, self._code_tester_command(state), node=NodeName.code_tester.value)
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.code_tester.value, run_result)
        planning_failure = self._planning_integrity_failure(
            iteration_id,
            node=NodeName.code_tester.value,
            run_id=run_id,
            action_hint="Code Tester 不得修改 PRD、testing_plan 或 context manifests。",
        )
        if planning_failure is not None:
            return planning_failure
        try:
            code_artifact: CodeTesterArtifact | None = None
            if run_result.returncode:
                code_artifact = self._try_code_tester_artifact(state, run_result)
                if code_artifact is not None:
                    self._node_event(
                        iteration_id,
                        "code_tester.nonzero_artifact.accepted",
                        NodeName.code_tester.value,
                        "验证命令异常但产物可用",
                        "Code Tester CLI 非零退出，但输出了合法验证产物。",
                        severity="warning",
                        run_id=run_id,
                    )
                    tester_pending = verification_from_code(code_artifact)
                else:
                    primary_notes = self._tester_failure_notes(run_result)
                    self._node_event(iteration_id, "code_tester.review_fallback.started", NodeName.code_tester.value, "启动代码审查兜底", primary_notes, severity="warning", run_id=run_id)
                    review_result = self._execute(
                        state,
                        self._code_tester_command(state, review_only=True, fallback_reason=primary_notes),
                        node=NodeName.code_tester.value,
                    )
                    if self._is_iteration_gone(iteration_id):
                        return self._abort_state()
                    review_run_id = self._record_run(iteration_id, NodeName.code_tester.value, review_result)
                    run_id = review_run_id
                    planning_failure = self._planning_integrity_failure(
                        iteration_id,
                        node=NodeName.code_tester.value,
                        run_id=run_id,
                        action_hint="Code Tester 不得修改 PRD、testing_plan 或 context manifests。",
                    )
                    if planning_failure is not None:
                        return planning_failure
                    if review_result.returncode:
                        notes = self._tester_failure_notes(run_result, review_result)
                        return self._route_tester_failure(
                            state,
                            review_run_id,
                            verification_from_code(
                                CodeTesterArtifact(
                                    verify_report="# Verify Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
                                    passed=False,
                                    failure_notes=notes,
                                )
                            ),
                        )
                    code_artifact = self._code_tester_artifact(state, review_result)
                    tester_pending = verification_from_code(code_artifact)
                    self._augment_review_fallback_artifact(tester_pending, primary_notes)
            else:
                self._node_event(iteration_id, "node.progress", NodeName.code_tester.value, "正在解析验证结果", "已收到 Code Tester 输出。", run_id=run_id)
                code_artifact = self._code_tester_artifact(state, run_result)
                tester_pending = verification_from_code(code_artifact)
            if code_artifact is None:
                raise ValueError("code tester artifact was not resolved")
            planning_failure = self._planning_integrity_failure(
                iteration_id,
                node=NodeName.code_tester.value,
                run_id=run_id,
                action_hint="Code Tester 不得修改 PRD、testing_plan 或 context manifests。",
            )
            if planning_failure is not None:
                return planning_failure
            self._write_tester_artifact(iteration_id, IterationDocs(self.docs_root(iteration_id)), tester_pending, run_id=run_id)
            gate_ok, gate_msg = self._run_artifact_gate(state)
            if not gate_ok:
                self._rollback_tester_adversarial(iteration_id, tester_pending.adversarial_tests)
                gate_artifact = self._gate_failed_artifact(tester_pending, gate_msg)
                self._node_event(
                    iteration_id,
                    "node.failed",
                    NodeName.code_tester.value,
                    "验证命令未通过",
                    gate_msg,
                    severity="error",
                    run_id=run_id,
                    action_hint="系统将按写权限分区自动回环；配置的 build/test 未通过时跳过 UI 验证。",
                )
                return self._route_tester_failure(state, run_id, gate_artifact)
            if not tester_pending.passed:
                notes = summarize_failure_notes(self._normalize_tester_artifact(tester_pending))
                self._node_event(
                    iteration_id,
                    "node.failed",
                    NodeName.code_tester.value,
                    "代码验证未通过",
                    notes,
                    severity="error",
                    run_id=run_id,
                    action_hint="系统将按写权限分区自动回环；Code Tester 未通过时跳过 UI 验证。",
                )
                return self._route_tester_failure(state, run_id, tester_pending)
            baseline = test_integrity_manifest(self.docs_root(iteration_id))
            self._update_iteration(iteration_id, test_integrity_baseline=baseline)
            self._node_event(iteration_id, "node.completed", NodeName.code_tester.value, "代码验证完成", "已建立测试基线，进入测试完整性检查。", severity="success", run_id=run_id)
            return {"pending_code_tester_json": tester_pending.model_dump_json(), "code_tester_run_id": run_id, "current_node": NodeName.integrity_check.value}
        except Exception as exc:
            planning_failure = self._planning_integrity_failure(
                iteration_id,
                node=NodeName.code_tester.value,
                run_id=run_id,
                action_hint="Code Tester 不得修改 PRD、testing_plan 或 context manifests。",
            )
            if planning_failure is not None:
                return planning_failure
            self._node_event(iteration_id, "node.failed", NodeName.code_tester.value, "验证产物无效", "Code Tester 输出无法被解析为合法 artifact。", severity="error", run_id=run_id)
            return self._route_artifact_self_retry(state, NodeName.code_tester.value, run_id, str(exc))


    def _ui_tester_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        pending = state.get("pending_code_tester_json")
        if not pending:
            return self._block(iteration_id, "code_tester.missing_artifact", None, "missing code tester artifact")
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.ui_tester.value, last_error=None)
        self._publish_snapshot(iteration_id)
        run_id = state.get("code_tester_run_id")
        try:
            baseline = VerificationArtifact.model_validate_json(pending)
            docs = IterationDocs(self.docs_root(iteration_id))
            self._node_event(
                iteration_id,
                "node.started",
                NodeName.ui_tester.value,
                "UI 验证已启动",
                "UI Tester Agent 将读取 testing_plan.md/PRD 并执行适用的 UI 验收检查。",
                run_id=run_id,
            )
            artifact, run_id = self._run_ui_tester_agent(state, baseline, docs, run_id=run_id)
            artifact = self._normalize_ui_tester_artifact(artifact)
            planning_failure = self._planning_integrity_failure(
                iteration_id,
                node=NodeName.ui_tester.value,
                run_id=run_id,
                action_hint="UI Tester 不得修改 PRD、testing_plan 或 context manifests。",
            )
            if planning_failure is not None:
                return planning_failure
            self._emit_ui_tester_result_events(iteration_id, artifact, run_id=run_id)
            self._write_tester_artifact(iteration_id, docs, artifact, run_id=run_id)
            problems = self._integrity_problems(iteration_id)
            if problems:
                self._node_event(iteration_id, "node.failed", NodeName.ui_tester.value, "验证后测试完整性失败", "; ".join(problems), severity="error", run_id=run_id, action_hint="Code Tester 只能写入 adversarial 和 UI recordings；请检查异常测试文件。")
                return self._block(iteration_id, "test_integrity.failed", run_id, "; ".join(problems))
            blocking_defects = self._blocking_defects(artifact.defects)
            if not artifact.passed and blocking_defects:
                notes = summarize_failure_notes(self._normalize_ui_tester_artifact(artifact))
                self._node_event(
                    iteration_id,
                    "node.failed",
                    NodeName.ui_tester.value,
                    "验证未通过",
                    notes,
                    severity="error",
                    run_id=run_id,
                    action_hint="查看失败说明，等待按写权限分区自动重试或处理阻断。",
                )
                return self._route_tester_failure(state, run_id, artifact)
            if not artifact.passed:
                artifact = artifact.model_copy(update={"passed": True})
            self._update_iteration(iteration_id, status=IterationStatus.awaiting_verify_approval.value, current_node=None, last_error=None)
            self._add_event(iteration_id, event_type="ui_tester.completed", payload={"result": "passed", "run_id": run_id})
            self._node_event(iteration_id, "node.completed", NodeName.ui_tester.value, "验证通过", "验证报告和交付建议已生成，等待规格复核和最终确认。", severity="success", run_id=run_id)
            return {"status": IterationStatus.awaiting_verify_approval.value, "route": "", "current_node": None, "verification_run_id": run_id}
        except Exception as exc:
            planning_failure = self._planning_integrity_failure(
                iteration_id,
                node=NodeName.ui_tester.value,
                run_id=run_id,
                action_hint="UI Tester 不得修改 PRD、testing_plan 或 context manifests。",
            )
            if planning_failure is not None:
                return planning_failure
            event_type = ui_spec_error_type(str(exc))
            hint = "查看验证产物。"
            title = "验证产物无效"
            body = "UI Tester 产物无法被解析。"
            self._node_event(iteration_id, "node.failed", NodeName.ui_tester.value, title, body, severity="error", run_id=run_id, action_hint=hint)
            if event_type == "artifact.invalid":
                return self._route_artifact_self_retry(state, NodeName.ui_tester.value, run_id, str(exc))
            return self._block(iteration_id, event_type, run_id, str(exc))


    def _planner_verify_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.testing.value, current_node=NodeName.planner_verify.value)
        self._node_event(iteration_id, "node.started", NodeName.planner_verify.value, "规格复核已启动", "Planner 正在机械检查验证报告是否满足基本结构要求。")
        planning_failure = self._planning_integrity_failure(iteration_id, node=NodeName.planner_verify.value)
        if planning_failure is not None:
            return planning_failure
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
