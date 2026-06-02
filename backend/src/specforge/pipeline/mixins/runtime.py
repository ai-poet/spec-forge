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
    _LIVE_CLI_MAX_CHARS = 64 * 1024
    _CLI_OUTPUT_FLUSH_INTERVAL = 0.25
    _PUBLIC_EVENT_TEXT_MAX_CHARS = 4 * 1024
    _PUBLIC_RUN_COMMAND_MAX_CHARS = 4 * 1024
    _PUBLIC_CLI_DISPLAY_EVENT_LIMIT = 120
    _PERSISTED_CLI_PHASES = {"session", "tool", "command", "file_change", "mcp", "todo", "hook", "retry", "result", "error"}
    _PREVIEW_CLI_PHASES = {"text", "thinking"}

    def _live_cli_snapshot(self, iteration_id: str) -> Optional[dict[str, str]]:
        with self._live_cli_lock:
            live = self._live_cli.get(iteration_id)
            if not live:
                return None
            return {"node": live["node"], "stdout": live["stdout"], "stderr": live["stderr"]}


    def _public_event_record(self, event: Any) -> dict[str, Any]:
        return {
            "id": event["id"],
            "iteration_id": event["iteration_id"],
            "type": event["type"],
            "payload": self._public_event_payload(json.loads(event["payload"])),
            "created_at": event["created_at"],
        }


    def _public_event_records(self, events: list[Any]) -> list[dict[str, Any]]:
        cli_display_seen = 0
        selected: list[Any] = []
        for event in reversed(events):
            if event["type"] == "cli.display":
                cli_display_seen += 1
                if cli_display_seen > self._PUBLIC_CLI_DISPLAY_EVENT_LIMIT:
                    continue
            selected.append(event)
        return [self._public_event_record(event) for event in reversed(selected)]


    def _public_event_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._compact_public_value(payload)


    def _public_run_record(self, iteration_id: str, run: Any) -> dict[str, Any]:
        stdout_bytes = run["stdout_bytes"] if "stdout_bytes" in run.keys() else len((run["stdout"] or "").encode("utf-8"))
        stderr_bytes = run["stderr_bytes"] if "stderr_bytes" in run.keys() else len((run["stderr"] or "").encode("utf-8"))
        return {
            "id": run["id"],
            "iteration_id": run["iteration_id"],
            "node": run["node"],
            "status": run["status"],
            "command": self._public_command(run["command"]),
            "exit_code": run["exit_code"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "duration_ms": run["duration_ms"] if "duration_ms" in run.keys() else None,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "logs_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/logs",
        }


    def _public_command(self, command: str) -> str:
        marker = "## SpecForge stage:"
        marker_index = command.find(marker)
        if marker_index >= 0:
            stage = command[marker_index + len(marker) :].splitlines()[0].strip()
            prefix = command[:marker_index].rstrip()
            return self._truncate_public_text(f"{prefix} {marker} {stage} [prompt omitted]", self._PUBLIC_RUN_COMMAND_MAX_CHARS)
        return self._truncate_public_text(command, self._PUBLIC_RUN_COMMAND_MAX_CHARS)


    def _compact_public_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._truncate_public_text(value, self._PUBLIC_EVENT_TEXT_MAX_CHARS)
        if isinstance(value, list):
            return [self._compact_public_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._compact_public_value(child)
                for key, child in value.items()
                if key != "raw_event"
            }
        return value


    @staticmethod
    def _truncate_public_text(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        omitted = len(value) - limit
        return f"{value[:limit]}\n...[truncated {omitted} chars]"


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
            self._live_cli_chunk_last_publish.pop(iteration_id, None)


    def _append_live_cli(self, iteration_id: str, stream: str, chunk: str) -> None:
        node = ""
        with self._live_cli_lock:
            live = self._live_cli.get(iteration_id)
            if live is None:
                return
            live[stream] += chunk
            if len(live[stream]) > self._LIVE_CLI_MAX_CHARS:
                live[stream] = live[stream][-self._LIVE_CLI_MAX_CHARS :]
            node = live["node"]
        self._maybe_publish_cli_output(iteration_id, node, stream, chunk)


    def _clear_live_cli(self, iteration_id: str) -> None:
        with self._live_cli_lock:
            self._live_cli.pop(iteration_id, None)
            self._live_cli_last_publish.pop(iteration_id, None)
            for key in list(self._live_cli_chunk_last_publish):
                if key == iteration_id or str(key).startswith(f"{iteration_id}:"):
                    self._live_cli_chunk_last_publish.pop(key, None)
            for key in list(self._live_cli_pending_chunks):
                if key[0] == iteration_id:
                    self._live_cli_pending_chunks.pop(key, None)


    def _maybe_publish_cli_output(self, iteration_id: str, node: str, stream: str, chunk: str) -> None:
        now = time.monotonic()
        publish_chunk: str | None = None
        with self._live_cli_lock:
            key = (iteration_id, stream)
            pending = self._live_cli_pending_chunks.setdefault(key, {"node": node, "chunk": ""})
            pending["node"] = node
            pending["chunk"] += chunk
            last = self._live_cli_chunk_last_publish.get(f"{iteration_id}:{stream}", 0.0)
            if now - last < self._CLI_OUTPUT_FLUSH_INTERVAL:
                return
            self._live_cli_chunk_last_publish[f"{iteration_id}:{stream}"] = now
            publish_chunk = pending["chunk"]
            pending["chunk"] = ""
        if not publish_chunk:
            return
        self._publish_cli_output_chunk(iteration_id, node, stream, publish_chunk)


    def _flush_cli_output(self, iteration_id: str) -> None:
        pending_items: list[tuple[str, str, str]] = []
        with self._live_cli_lock:
            for key, pending in list(self._live_cli_pending_chunks.items()):
                if key[0] != iteration_id:
                    continue
                chunk = pending.get("chunk", "")
                if chunk:
                    pending_items.append((pending.get("node") or "", key[1], chunk))
                self._live_cli_pending_chunks.pop(key, None)
        for node, stream, chunk in pending_items:
            self._publish_cli_output_chunk(iteration_id, node, stream, chunk)


    def _publish_cli_output_chunk(self, iteration_id: str, node: str, stream: str, chunk: str) -> None:
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
        started_at = iso(run_result.started_at) if run_result.started_at else None
        finished_at = iso(run_result.finished_at) if run_result.finished_at else iso(utcnow())
        run_id = self.db.add_run(
            iteration_id,
            node=node,
            status="failed" if run_result.returncode else "success",
            command=" ".join(run_result.command),
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            exit_code=run_result.returncode,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=run_result.duration_ms,
            stdout_bytes=run_result.stdout_bytes,
            stderr_bytes=run_result.stderr_bytes,
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
        self.broker.publish(iteration_id, EventEnvelope(type="event", event=self._public_event_record(event)))


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
            self._flush_cli_output(iteration_id)
            if not self._is_iteration_gone(iteration_id):
                self._publish_snapshot(iteration_id)


    def _cli_display_event(self, iteration_id: str, event: CliDisplayEvent) -> None:
        if event.phase in self._PERSISTED_CLI_PHASES:
            self._add_event(iteration_id, event_type="cli.display", payload=event.payload(include_raw=False))
            return
        if event.phase in self._PREVIEW_CLI_PHASES:
            now = time.monotonic()
            key = f"{iteration_id}:cli.display:{event.node}:{event.phase}"
            with self._live_cli_lock:
                last = self._live_cli_chunk_last_publish.get(key, 0.0)
                if now - last < 1.0:
                    return
                self._live_cli_chunk_last_publish[key] = now
            try:
                self.broker.publish(
                    iteration_id,
                    EventEnvelope(
                        type="event",
                        event={
                            "id": f"preview_{event.node}_{event.phase}_{int(now * 1000)}",
                            "iteration_id": iteration_id,
                            "type": "cli.display",
                            "payload": event.payload(include_raw=False),
                            "created_at": iso(utcnow()),
                        },
                    ),
                )
            except Exception:
                pass


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
            "artifact.self_max_retries": "Agent 产物自修已达上限",
            "ui_spec.invalid": "Agent 产物格式无效",
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
            "artifact.self_max_retries": "查看最后一次产物错误和原始日志，必要时人工修正 prompt 或 artifact schema。",
            "ui_spec.invalid": "查看对应 agent 的原始日志，确认输出是否为合法 JSON artifact。",
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
