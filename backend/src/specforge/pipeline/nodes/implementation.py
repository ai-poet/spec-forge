from __future__ import annotations

from ...core.models import IterationStatus, NodeName
from ...documents.docs_io import IterationDocs
from ..state import PipelineState


class ImplementationNodesMixin:

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
        planning_failure = self._planning_integrity_failure(
            iteration_id,
            node=NodeName.coder.value,
            run_id=run_id,
            action_hint="Coder 不得修改 PRD、testing_plan 或 context manifests。",
        )
        if planning_failure is not None:
            return planning_failure
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.coder.value, "实现失败", "Coder CLI 执行失败。", severity="error", run_id=run_id, action_hint=self._cli_failure_action_hint(run_result, context="同时检查工作区权限。"))
            return self._block(iteration_id, "coder.failed", run_id, run_result.stderr)

        try:
            self._node_event(iteration_id, "node.progress", NodeName.coder.value, "正在解析实现结果", "已收到 Coder 输出，正在读取变更摘要和澄清请求。", run_id=run_id)
            artifact = self._coder_artifact(state, run_result)
        except Exception as exc:
            self._node_event(iteration_id, "node.failed", NodeName.coder.value, "实现产物无效", "Coder 输出无法被解析为合法 artifact。", severity="error", run_id=run_id, action_hint="查看 Coder 原始日志，要求模型只输出符合 schema 的 JSON。")
            return self._route_artifact_self_retry(state, NodeName.coder.value, run_id, str(exc))

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

        planning_failure = self._planning_integrity_failure(
            iteration_id,
            node=NodeName.coder.value,
            run_id=run_id,
            action_hint="Coder 不得修改 PRD、testing_plan 或 context manifests。",
        )
        if planning_failure is not None:
            return planning_failure

        self._add_event(
            iteration_id,
            event_type="coder.completed",
            payload={"changed_paths": artifact.changed_paths, "summary": artifact.summary, "run_id": run_id},
        )
        self._node_event(iteration_id, "node.completed", NodeName.coder.value, "实现完成", artifact.summary or "代码实现已完成，准备进入代码验证。", severity="success", run_id=run_id)
        return {"status": IterationStatus.testing.value, "route": "", "current_node": NodeName.code_tester.value, "coder_run_id": run_id}


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
                action_hint=self._cli_failure_action_hint(run_result),
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
            return self._route_artifact_self_retry(state, NodeName.planner_clarification.value, run_id, str(exc))

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
        self._node_event(iteration_id, "node.started", NodeName.integrity_check.value, "测试完整性检查已启动", "正在确认 Code Tester 编写的测试没有被未授权修改。")
        problems = self._integrity_problems(iteration_id)
        if problems:
            self._node_event(iteration_id, "node.failed", NodeName.integrity_check.value, "测试完整性失败", "; ".join(problems), severity="error", action_hint="检查测试文件是否被意外修改。")
            return self._block(iteration_id, "test_integrity.failed", None, "; ".join(problems))
        planning_failure = self._planning_integrity_failure(iteration_id, node=NodeName.integrity_check.value)
        if planning_failure is not None:
            return planning_failure
        self._add_event(iteration_id, event_type="test_integrity.passed", payload={"stage": "after_tester"})
        self._node_event(iteration_id, "node.completed", NodeName.integrity_check.value, "测试完整性通过", "测试基线未被未授权修改，可以进入 UI 验证。", severity="success")
        return {"status": IterationStatus.testing.value, "current_node": NodeName.ui_tester.value}
