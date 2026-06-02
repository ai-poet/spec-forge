from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from ...agents.cli_event_presenter import CliDisplayEvent
from ...agents.cli_runner import CLIResult
from ...core.config import settings
from ...core.models import IterationStatus, Mode
from ...documents.docs_io import checksum
from ...runtime.events import EventEnvelope
from ...storage.db import iso, utcnow

from ..state import PipelineState


class PipelineRuntimeMixin:

    def _live_cli_snapshot(self, iteration_id: str) -> Optional[dict[str, str]]:
        with self._live_cli_lock:
            live = self._live_cli.get(iteration_id)
            if not live:
                return None
            return {"node": live["node"], "stdout": live["stdout"], "stderr": live["stderr"]}


    def _reset_live_cli(self, iteration_id: str, node: str, *, continuing: bool = False) -> None:
        with self._live_cli_lock:
            if continuing and iteration_id in self._live_cli:
                existing = self._live_cli[iteration_id]
                existing["node"] = node
                existing["stdout"] += f"\n--- {node} ---\n"
                existing["stderr"] += f"\n--- {node} ---\n"
            else:
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
            "planning_integrity.failed": "规划文档完整性失败",
            "prd_planner.failed": "PRD 规划失败",
            "coder.failed": "实现节点失败",
            "code_tester.max_retries": "验证重试已达上限",
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
            "planning_integrity.failed": "检查 PRD、testing_plan 与 context manifests 是否被非规划节点修改；必要时回到 Test Planner 重新生成 baseline。",
            "prd_planner.failed": "检查 Claude CLI、模型配置和 API 凭据。",
            "coder.failed": "检查 Claude CLI、工作区权限和失败日志。",
            "code_tester.max_retries": "查看最后一次验证失败说明，必要时人工调整需求或实现。",
            "clarification.max_retries": "补充需求细节或约束后重新启动迭代。",
            "planner_verify.max_retries": "检查验证报告结构，确保包含测试摘要和通过信息。",
            "job.failed": "查看后端日志，确认后台 worker 和 LangGraph checkpoint 状态。",
        }
        return hints.get(event_type, "查看事件流和运行日志，处理阻断后重新创建或重试迭代。")
