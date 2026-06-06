from __future__ import annotations

from langgraph.types import interrupt

from ...core.contracts import ui_spec_error_type
from ...core.models import IterationStatus, NodeName
from ...documents.docs_io import IterationDocs, planning_integrity_manifest
from ...documents.docs_scaffold import append_iteration_log
from ..state import PipelineState


class PlanningNodesMixin:

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
        is_continuing = self._planning_session_started(state)
        self._reset_live_cli(iteration_id, NodeName.planner_discovery.value, continuing=is_continuing)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.planner_discovery.value,
            "需求澄清已启动" if not is_continuing else "需求澄清续接中",
            "Planner 正在分析大需求，必要时将向您提出单个澄清问题。" if not is_continuing else "Planner 正在根据用户答案继续澄清。",
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
        self._sync_planning_session_from_run(state, run_result)
        self._mark_planning_session_started(state)

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
            return self._route_artifact_self_retry(state, NodeName.planner_discovery.value, run_id, str(exc))

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
        self._update_iteration(
            iteration_id,
            status=IterationStatus.planning.value,
            current_node=NodeName.planner_discovery.value,
        )
        return {
            "discovery_qa": discovery_qa,
            "pending_discovery_question": None,
            "pending_discovery_options": [],
            "pending_discovery_assumptions": [],
            "status": IterationStatus.planning.value,
            "route": "",
            "current_node": NodeName.planner_discovery.value,
        }


    def _prd_planner_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        self._update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.prd_planner.value, last_error=None)
        self._reset_live_cli(iteration_id, NodeName.prd_planner.value, continuing=True)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.prd_planner.value,
            "PRD 规划已启动",
            "正在根据澄清后的需求生成 PRD 与上下文清单。",
        )
        self._add_event(iteration_id, event_type="iteration.started", payload={"status": "planning"})
        run_result = self._execute(state, self._prd_planner_command(state), node=NodeName.prd_planner.value)
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.prd_planner.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.prd_planner.value, "PRD 规划失败", "PRD Planner CLI 执行失败。", severity="error", run_id=run_id, action_hint="查看运行日志，确认 CLI 可用并能返回 JSON artifact。")
            return self._block(iteration_id, "prd_planner.failed", run_id, run_result.stderr)
        self._sync_planning_session_from_run(state, run_result)
        self._mark_planning_session_started(state)
        try:
            self._node_event(iteration_id, "node.progress", NodeName.prd_planner.value, "正在解析 PRD 产物", "已收到 PRD Planner 输出，正在写入 prd.md 与 context manifests。", run_id=run_id)
            artifact = self._prd_planner_artifact(state, run_result)
            docs = IterationDocs(self.docs_root(iteration_id))
            docs.ensure()
            self._write_prd_planner_artifact(iteration_id, docs, artifact, run_id=run_id)
            self._update_iteration(iteration_id, test_integrity_baseline={}, planning_integrity_baseline={}, last_error=None)
            self._add_event(iteration_id, event_type="prd_planner.completed", payload={"run_id": run_id})
            self._node_event(iteration_id, "node.completed", NodeName.prd_planner.value, "PRD 规划完成", "prd.md 与上下文清单已生成，进入测试规划。", severity="success", run_id=run_id)
            return {"status": IterationStatus.planning.value, "current_node": None, "prd_planner_run_id": run_id, "route": "test_planner"}
        except Exception as exc:
            self._node_event(iteration_id, "node.failed", NodeName.prd_planner.value, "PRD 产物无效", "PRD Planner 输出无法被解析为合法 artifact。", severity="error", run_id=run_id, action_hint="查看 PRD Planner 原始日志，要求模型只输出符合 schema 的 JSON。")
            return self._route_artifact_self_retry(state, NodeName.prd_planner.value, run_id, str(exc))


    def _test_planner_node(self, state: PipelineState) -> PipelineState:
        iteration_id = state["iteration_id"]
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        retry_counts = dict(state.get("retry_counts") or {})
        is_retry = retry_counts.get("test_planner_self", 0) > 0
        self._update_iteration(iteration_id, status=IterationStatus.planning.value, current_node=NodeName.test_planner.value, retry_counts=retry_counts, last_error=None)
        self._reset_live_cli(iteration_id, NodeName.test_planner.value, continuing=True)
        self._publish_snapshot(iteration_id)
        self._node_event(
            iteration_id,
            "node.started",
            NodeName.test_planner.value,
            "测试规划已启动" if not is_retry else "测试规划正在重试",
            "正在编写 testing_plan 与受保护测试（Coder 之前）。" if not is_retry else "正在根据验证失败修订受保护测试。",
        )
        run_result = self._execute(state, self._test_planner_command(state), node=NodeName.test_planner.value)
        if self._is_iteration_gone(iteration_id):
            return self._abort_state()
        run_id = self._record_run(iteration_id, NodeName.test_planner.value, run_result)
        if run_result.returncode:
            self._node_event(iteration_id, "node.failed", NodeName.test_planner.value, "测试规划失败", "Test Planner CLI 执行失败。", severity="error", run_id=run_id, action_hint="查看运行日志。")
            return self._block(iteration_id, "test_planner.failed", run_id, run_result.stderr)
        self._sync_planning_session_from_run(state, run_result)
        self._mark_planning_session_started(state)
        try:
            artifact = self._test_planner_artifact(state, run_result)
            docs = IterationDocs(self.docs_root(iteration_id))
            docs.ensure()
            self._write_test_planner_artifact(iteration_id, docs, artifact, run_id=run_id)
            planning_baseline = planning_integrity_manifest(docs.root)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.coding.value,
                current_node=None,
                planning_integrity_baseline=planning_baseline,
                last_error=None,
            )
            self._add_event(iteration_id, event_type="test_planner.completed", payload={"documents": 1, "run_id": run_id})
            self._node_event(
                iteration_id,
                "node.completed",
                NodeName.test_planner.value,
                "测试规划完成",
                "已生成 testing_plan，测试文件将由 Code Tester 在实现后编写，进入实现。",
                severity="success",
                run_id=run_id,
            )
            return {"status": IterationStatus.coding.value, "current_node": None, "test_planner_run_id": run_id, "route": "coder"}
        except Exception as exc:
            event_type = ui_spec_error_type(str(exc))
            hint = "查看 Test Planner 原始日志。"
            title = "测试规划产物无效"
            body = "Test Planner 输出无法被解析为合法 artifact。"
            self._node_event(iteration_id, "node.failed", NodeName.test_planner.value, title, body, severity="error", run_id=run_id, action_hint=hint)
            if event_type == "artifact.invalid":
                return self._route_artifact_self_retry(state, NodeName.test_planner.value, run_id, str(exc))
            return self._block(iteration_id, event_type, run_id, str(exc))
