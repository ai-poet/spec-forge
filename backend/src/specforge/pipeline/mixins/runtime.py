from __future__ import annotations

import json
import time
import inspect
from collections import deque
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from ...agents.cli_event_presenter import CliDisplayEvent
from ...agents.cli_runner import CLIResult
from ...agents.providers import AgentCommand, worker_ref_from_result
from ...core.config import settings
from ...core.models import IterationStatus, Mode
from ...context_profiles import context_package_for_run, workflow_snapshot
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
    _PUBLIC_EVENT_LIMIT = 300
    _PUBLIC_RUN_LIMIT = 100
    _RUN_LOG_PAGE_SIZE_MAX = 500
    _RUN_OUTPUT_PREVIEW_MAX_CHARS = 8 * 1024
    _EXPORT_LOG_HEAD_LIMIT = 20
    _EXPORT_LOG_TAIL_LIMIT = 80
    _EXPORT_LOG_DIAGNOSTIC_LIMIT = 80
    _EXPORT_LOG_LINE_MAX_CHARS = 1200
    _EXPORT_LOG_DIAGNOSTIC_TERMS = ("error", "failed", "exception", "traceback", "timeout", "cancelled")
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
            "provider": run["provider"] if "provider" in run.keys() else None,
            "session_id": run["session_id"] if "session_id" in run.keys() else None,
            "session_mode": run["session_mode"] if "session_mode" in run.keys() else None,
            "prompt_hash": run["prompt_hash"] if "prompt_hash" in run.keys() else None,
            "prompt_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/prompt-bundle" if "prompt_path" in run.keys() and run["prompt_path"] else None,
            "raw_log_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/logs",
            "worker_ref_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/worker-ref" if "worker_ref_path" in run.keys() and run["worker_ref_path"] else None,
            "context_package_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/context-package",
            "supports_continue": bool(run["session_id"]) if "session_id" in run.keys() else False,
            "timed_out": bool(run["timed_out"]) if "timed_out" in run.keys() else False,
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
        metadata = dict(run_result.metadata or {})
        command_meta = metadata.get("agent_command") if isinstance(metadata.get("agent_command"), AgentCommand) else None
        run_id = str(metadata.get("run_id") or f"run_{uuid4().hex[:8]}")
        cwd = metadata.get("cwd")
        cwd_path = Path(cwd) if isinstance(cwd, str) and cwd else None
        files = self._persist_run_observability(iteration_id, run_id, node, run_result, command_meta, cwd_path)
        session_id = files.get("session_id")
        stdout_preview = self._truncate_public_text(run_result.stdout or "", self._RUN_OUTPUT_PREVIEW_MAX_CHARS)
        stderr_preview = self._truncate_public_text(run_result.stderr or "", self._RUN_OUTPUT_PREVIEW_MAX_CHARS)
        run_id = self.db.add_run(
            iteration_id,
            run_id=run_id,
            node=node,
            status="failed" if run_result.returncode else "success",
            command=command_meta.public_command() if command_meta else " ".join(run_result.command),
            stdout=stdout_preview,
            stderr=stderr_preview,
            exit_code=run_result.returncode,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=run_result.duration_ms,
            stdout_bytes=run_result.stdout_bytes,
            stderr_bytes=run_result.stderr_bytes,
            provider=command_meta.provider if command_meta else None,
            session_id=session_id,
            session_mode=command_meta.session_mode if command_meta else None,
            prompt_hash=command_meta.prompt_bundle.prompt_hash if command_meta else None,
            prompt_path=files.get("prompt_path"),
            raw_log_path=files.get("raw_log_path"),
            worker_ref_path=files.get("worker_ref_path"),
            timed_out=run_result.timed_out,
        )
        if command_meta and command_meta.continue_requested and not session_id:
            self._add_event(
                iteration_id,
                event_type="provider.continue_fallback",
                payload={
                    "run_id": run_id,
                    "node": node,
                    "provider": command_meta.provider,
                    "reason": command_meta.continue_fallback_reason or "session ref was not captured; executed as a fresh direct CLI call",
                },
            )
        self._clear_live_cli(iteration_id)
        self._publish_snapshot(iteration_id)
        return run_id


    def _run_observability_dir(self, iteration_id: str, run_id: str) -> Path:
        path = self.project_root(iteration_id) / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path


    def _persist_run_observability(
        self,
        iteration_id: str,
        run_id: str,
        node: str,
        run_result: CLIResult,
        command: AgentCommand | None,
        cwd: Path | None,
    ) -> dict[str, str | None]:
        run_dir = self._run_observability_dir(iteration_id, run_id)
        raw_log_meta = run_result.metadata.get("raw_log_path")
        raw_log_path = Path(raw_log_meta) if isinstance(raw_log_meta, str) and raw_log_meta else run_dir / "raw.jsonl"
        if not raw_log_path.exists():
            self._write_raw_log(raw_log_path, node=node, run_result=run_result)
        prompt_path: Path | None = None
        worker_ref_path: Path | None = None
        session_id: str | None = None
        if command:
            prompt_path = run_dir / "prompt-bundle.json"
            prompt_path.write_text(json.dumps(command.prompt_bundle.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
            worker_ref = worker_ref_from_result(command=command, stdout=run_result.stdout, stderr=run_result.stderr, cwd=cwd)
            payload = worker_ref.payload()
            ref = payload.get("continueRef")
            if isinstance(ref, dict):
                session_id = ref.get("sessionId") or ref.get("threadId")
                if session_id is not None:
                    session_id = str(session_id)
            worker_ref_path = run_dir / "worker-ref.json"
            worker_ref_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "raw_log_path": str(raw_log_path),
            "prompt_path": str(prompt_path) if prompt_path else None,
            "worker_ref_path": str(worker_ref_path) if worker_ref_path else None,
            "session_id": session_id,
        }


    def _write_raw_log(self, path: Path, *, node: str, run_result: CLIResult) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for stream_name, text in (("stdout", run_result.stdout or ""), ("stderr", run_result.stderr or "")):
                for index, line in enumerate(text.splitlines()):
                    handle.write(
                        json.dumps(
                            {
                                "stream": stream_name,
                                "line": index + 1,
                                "node": node,
                                "text": line,
                                "created_at": iso(run_result.started_at or utcnow()),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )


    def run_logs_page(self, iteration_id: str, run_id: str, *, offset: int = 0, limit: int = 200) -> dict[str, Any]:
        run = self._find_run(iteration_id, run_id)
        raw_path = run["raw_log_path"] if "raw_log_path" in run.keys() else None
        limit = max(1, min(limit, self._RUN_LOG_PAGE_SIZE_MAX))
        if raw_path and Path(raw_path).is_file():
            return self._read_raw_log_page(Path(raw_path), offset=offset, limit=limit)
        lines: list[dict[str, Any]] = []
        for stream in ("stdout", "stderr"):
            text = run[stream] or ""
            for line_no, text_line in enumerate(text.splitlines(), start=1):
                lines.append({"stream": stream, "line": line_no, "text": text_line})
        total = len(lines)
        return {"items": lines[offset : offset + limit], "offset": offset, "limit": limit, "total": total, "has_more": offset + limit < total}

    def export_iteration_logs(self, iteration_id: str, *, mode: str = "full") -> dict[str, Any]:
        self._require_iteration(iteration_id)
        if mode == "summary":
            return self._export_iteration_logs_summary(iteration_id)
        runs = self.db.list_runs(iteration_id)
        run_logs: list[dict[str, Any]] = []
        for run in runs:
            run_id = run["id"]
            all_items: list[dict[str, Any]] = []
            offset = 0
            while True:
                page = self.run_logs_page(iteration_id, run_id, offset=offset, limit=self._RUN_LOG_PAGE_SIZE_MAX)
                all_items.extend(page["items"])
                if not page["has_more"]:
                    break
                offset += len(page["items"])
            run_logs.append({
                "run_id": run_id,
                "node": run["node"],
                "status": run["status"],
                "provider": run["provider"] if "provider" in run.keys() else None,
                "started_at": run["started_at"],
                "finished_at": run["finished_at"] if "finished_at" in run.keys() else None,
                "duration_ms": run["duration_ms"] if "duration_ms" in run.keys() else None,
                "exit_code": run["exit_code"] if "exit_code" in run.keys() else None,
                "stdout_bytes": run["stdout_bytes"] if "stdout_bytes" in run.keys() else 0,
                "stderr_bytes": run["stderr_bytes"] if "stderr_bytes" in run.keys() else 0,
                "logs": {"items": all_items, "total": len(all_items)},
            })
        return {
            "iteration_id": iteration_id,
            "exported_at": iso(utcnow()),
            "runs": run_logs,
        }


    def _export_iteration_logs_summary(self, iteration_id: str) -> dict[str, Any]:
        runs = self.db.list_runs(iteration_id)
        run_logs: list[dict[str, Any]] = []
        total_stdout_bytes = 0
        total_stderr_bytes = 0
        failed_run_count = 0
        has_truncated = False
        for run in runs:
            stdout_bytes = run["stdout_bytes"] if "stdout_bytes" in run.keys() else len((run["stdout"] or "").encode("utf-8"))
            stderr_bytes = run["stderr_bytes"] if "stderr_bytes" in run.keys() else len((run["stderr"] or "").encode("utf-8"))
            total_stdout_bytes += stdout_bytes
            total_stderr_bytes += stderr_bytes
            if run["status"] != "success":
                failed_run_count += 1
            log_summary = self._summarize_run_logs(run)
            has_truncated = has_truncated or bool(log_summary.get("truncated"))
            run_logs.append({
                "run_id": run["id"],
                "node": run["node"],
                "status": run["status"],
                "provider": run["provider"] if "provider" in run.keys() else None,
                "started_at": run["started_at"],
                "finished_at": run["finished_at"] if "finished_at" in run.keys() else None,
                "duration_ms": run["duration_ms"] if "duration_ms" in run.keys() else None,
                "exit_code": run["exit_code"] if "exit_code" in run.keys() else None,
                "timed_out": bool(run["timed_out"]) if "timed_out" in run.keys() else False,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
                "logs_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/logs",
                "raw_log_url": f"/api/iterations/{iteration_id}/runs/{run['id']}/logs",
                "prompt_hash": run["prompt_hash"] if "prompt_hash" in run.keys() else None,
                "logs": {"summary": log_summary},
            })
        return {
            "iteration_id": iteration_id,
            "exported_at": iso(utcnow()),
            "mode": "summary",
            "summary": {
                "run_count": len(runs),
                "failed_run_count": failed_run_count,
                "stdout_bytes": total_stdout_bytes,
                "stderr_bytes": total_stderr_bytes,
                "has_truncated": has_truncated,
            },
            "runs": run_logs,
        }


    def _summarize_run_logs(self, run: Any) -> dict[str, Any]:
        head: list[dict[str, Any]] = []
        tail: deque[dict[str, Any]] = deque(maxlen=self._EXPORT_LOG_TAIL_LIMIT)
        diagnostics: list[dict[str, Any]] = []
        seen_diagnostics: set[tuple[str, str]] = set()
        total = 0
        text_truncated = False
        diagnostics_truncated = False

        for item in self._iter_run_log_items(run):
            total += 1
            compact_item, item_truncated = self._compact_export_log_item(item)
            text_truncated = text_truncated or item_truncated
            if len(head) < self._EXPORT_LOG_HEAD_LIMIT:
                head.append(compact_item)
            tail.append(compact_item)
            if self._is_diagnostic_log_line(compact_item):
                key = self._export_log_item_key(compact_item, fallback_line=total)
                if key in seen_diagnostics:
                    continue
                if len(diagnostics) >= self._EXPORT_LOG_DIAGNOSTIC_LIMIT:
                    diagnostics_truncated = True
                    continue
                seen_diagnostics.add(key)
                diagnostics.append(compact_item)

        head_keys = {self._export_log_item_key(item, fallback_line=index) for index, item in enumerate(head, start=1)}
        tail_items = [
            item
            for index, item in enumerate(tail, start=max(total - len(tail) + 1, 1))
            if self._export_log_item_key(item, fallback_line=index) not in head_keys
        ]
        omitted_middle_count = max(0, total - len(head) - len(tail_items))
        truncated = (
            omitted_middle_count > 0
            or text_truncated
            or diagnostics_truncated
        )
        return {
            "items_total": total,
            "head": head,
            "tail": tail_items,
            "diagnostics": diagnostics,
            "omitted_middle_count": omitted_middle_count,
            "limits": {
                "head": self._EXPORT_LOG_HEAD_LIMIT,
                "tail": self._EXPORT_LOG_TAIL_LIMIT,
                "diagnostics": self._EXPORT_LOG_DIAGNOSTIC_LIMIT,
                "text_chars": self._EXPORT_LOG_LINE_MAX_CHARS,
            },
            "truncated": truncated,
            "text_truncated": text_truncated,
            "diagnostics_truncated": diagnostics_truncated,
        }


    def _iter_run_log_items(self, run: Any):
        raw_path = run["raw_log_path"] if "raw_log_path" in run.keys() else None
        if raw_path and Path(raw_path).is_file():
            with Path(raw_path).open("r", encoding="utf-8") as handle:
                for total, raw in enumerate(handle, start=1):
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"stream": "stdout", "line": total, "text": raw.rstrip("\n")}
                    yield payload
            return
        for stream in ("stdout", "stderr"):
            text = run[stream] or ""
            for line_no, text_line in enumerate(text.splitlines(), start=1):
                yield {"stream": stream, "line": line_no, "text": text_line}


    def _compact_export_log_item(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        compact = dict(item)
        text = str(compact.get("text", ""))
        if len(text) <= self._EXPORT_LOG_LINE_MAX_CHARS:
            compact["text"] = text
            return compact, False
        omitted = len(text) - self._EXPORT_LOG_LINE_MAX_CHARS
        compact["text"] = f"{text[:self._EXPORT_LOG_LINE_MAX_CHARS]}\n...[truncated {omitted} chars]"
        compact["text_truncated"] = True
        return compact, True


    def _export_log_item_key(self, item: dict[str, Any], *, fallback_line: int) -> tuple[str, str]:
        return (str(item.get("stream", "")), str(item.get("line", fallback_line)))


    def _is_diagnostic_log_line(self, item: dict[str, Any]) -> bool:
        stream = str(item.get("stream", ""))
        if stream == "stderr":
            return True
        text = str(item.get("text", "")).lower()
        return any(term in text for term in self._EXPORT_LOG_DIAGNOSTIC_TERMS)


    def _read_raw_log_page(self, path: Path, *, offset: int, limit: int) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        total = 0
        with path.open("r", encoding="utf-8") as handle:
            for total, raw in enumerate(handle, start=1):
                index = total - 1
                if index < offset:
                    continue
                if len(items) >= limit:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"stream": "stdout", "line": total, "text": raw.rstrip("\n")}
                items.append(payload)
        return {"items": items, "offset": offset, "limit": limit, "total": total, "has_more": offset + limit < total}


    def run_prompt_bundle(self, iteration_id: str, run_id: str) -> dict[str, Any]:
        run = self._find_run(iteration_id, run_id)
        path = run["prompt_path"] if "prompt_path" in run.keys() else None
        if not path or not Path(path).is_file():
            raise FileNotFoundError(run_id)
        return json.loads(Path(path).read_text(encoding="utf-8"))


    def run_worker_ref(self, iteration_id: str, run_id: str) -> dict[str, Any]:
        run = self._find_run(iteration_id, run_id)
        path = run["worker_ref_path"] if "worker_ref_path" in run.keys() else None
        if not path or not Path(path).is_file():
            raise FileNotFoundError(run_id)
        return json.loads(Path(path).read_text(encoding="utf-8"))


    def workflow_snapshot(self, iteration_id: str) -> dict[str, Any]:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        return workflow_snapshot(project=project, iteration=row)


    def run_context_package(self, iteration_id: str, run_id: str) -> dict[str, Any]:
        row = self._require_iteration(iteration_id)
        project = self.db.get_project_row(row["project_id"]) if row["project_id"] else None
        if project is None or not project["root_path"]:
            raise FileNotFoundError("project root is not available")
        run = self._find_run(iteration_id, run_id)
        return context_package_for_run(
            project_root=Path(project["root_path"]),
            iteration_root=self.project_root(iteration_id),
            docs_root=self.docs_root(iteration_id),
            run=run,
            documents=self.db.list_documents(iteration_id),
            events=self.db.list_events(iteration_id),
        )


    def _find_run(self, iteration_id: str, run_id: str) -> Any:
        for run in self.db.list_runs(iteration_id):
            if run["id"] == run_id:
                return run
        raise KeyError(run_id)


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


    def _timeout_stop_state(
        self,
        iteration_id: str,
        node: str,
        run_result: CLIResult,
        run_id: Optional[str],
    ) -> Optional[PipelineState]:
        if not run_result.timed_out:
            return None
        reason = self._format_cli_timeout(run_result)
        self._node_event(
            iteration_id,
            "node.timeout",
            node,
            "CLI 执行超时",
            reason,
            severity="warning",
            run_id=run_id,
            action_hint="该迭代已转为可恢复 stopped；服务重启后会从当前节点自动恢复，或可手动点击恢复。",
        )
        self.stop_iteration(iteration_id, reason)
        return {"status": IterationStatus.stopped.value, "route": "", "current_node": None, "blocked_reason": None}


    @staticmethod
    def _format_cli_timeout(run_result: CLIResult) -> str:
        diagnostic = " ".join((run_result.stderr or run_result.stdout or "").split())
        prefix = "CLI timed out"
        if "idle timed out" in diagnostic.lower():
            prefix = "CLI idle timed out"
        if diagnostic:
            return f"{prefix}; stopped for automatic recovery. {diagnostic}"
        return f"{prefix}; stopped for automatic recovery."


    def _execute(
        self,
        state: PipelineState,
        command: list[str] | AgentCommand,
        *,
        node: str | None = None,
    ) -> CLIResult:
        iteration_id = state["iteration_id"]
        if node is None:
            row = self._require_iteration(iteration_id)
            current_node = row["current_node"] or "agent"
        else:
            current_node = node
        agent_command = command if isinstance(command, AgentCommand) else None
        command_list = agent_command.command if agent_command else command
        use_codex_sdk = bool(self._is_real_cli(state.get("mode")) and agent_command and agent_command.provider == "codex")
        runner = self.codex_runner if use_codex_sdk else self.real_runner if self._is_real_cli(state.get("mode")) else self.dry_runner
        self._publish_snapshot(iteration_id)
        seen_output = {"stdout": False, "stderr": False}
        seen_cli_events: set[str] = set()
        run_id = f"run_{uuid4().hex[:8]}"
        raw_log_path = self._run_observability_dir(iteration_id, run_id) / "raw.jsonl"
        raw_log_counts = {"stdout": 0, "stderr": 0}
        raw_log_handle = raw_log_path.open("w", encoding="utf-8")
        cli_presenter = type(self.cli_presenter)()

        def write_raw_log(stream: str, chunk: str) -> None:
            for text_line in chunk.splitlines():
                raw_log_counts[stream] = raw_log_counts.get(stream, 0) + 1
                raw_log_handle.write(
                    json.dumps(
                        {
                            "stream": stream,
                            "line": raw_log_counts[stream],
                            "node": str(current_node),
                            "text": text_line,
                            "created_at": iso(utcnow()),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            raw_log_handle.flush()

        def on_output(stream: str, chunk: str) -> None:
            if not chunk:
                return
            write_raw_log(stream, chunk)
            self._append_live_cli(iteration_id, stream, chunk)
            if not chunk.strip():
                return
            if self._is_real_cli(state.get("mode")):
                cli_events = cli_presenter.present_chunk(chunk, node=str(current_node))
                has_pending_cli_text = cli_presenter.has_pending_text(node=str(current_node))
                publish_cli_display_events(cli_events)
                if cli_events or has_pending_cli_text:
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

        def publish_cli_display_events(events: list[CliDisplayEvent]) -> None:
            for event in events:
                key = event.key
                if key in seen_cli_events and event.phase not in ("text", "thinking"):
                    continue
                if event.phase not in ("text", "thinking"):
                    seen_cli_events.add(key)
                self._cli_display_event(iteration_id, event)

        try:
            cwd = self._execution_cwd(state)
            kwargs: dict[str, Any] = {"iteration_id": iteration_id}
            if use_codex_sdk:
                try:
                    codex_params = inspect.signature(runner.run_agent).parameters
                except (TypeError, ValueError):
                    codex_params = {}
                if "timeout_seconds" in codex_params:
                    kwargs["timeout_seconds"] = settings.cli_timeout_seconds or None
                if "idle_timeout_seconds" in codex_params:
                    kwargs["idle_timeout_seconds"] = settings.cli_idle_timeout_seconds or None
                if "capture_max_chars" in codex_params:
                    kwargs["capture_max_chars"] = settings.cli_result_max_chars
                result = runner.run_agent(
                    agent_command,
                    cwd=cwd,
                    on_output=on_output,
                    **kwargs,
                )
            else:
                try:
                    runner_params = inspect.signature(runner.run).parameters
                except (TypeError, ValueError):
                    runner_params = {"timeout_seconds": None, "idle_timeout_seconds": None, "capture_max_chars": None}
                if "timeout_seconds" in runner_params:
                    kwargs["timeout_seconds"] = settings.cli_timeout_seconds or None
                if "idle_timeout_seconds" in runner_params:
                    kwargs["idle_timeout_seconds"] = settings.cli_idle_timeout_seconds or None
                if "capture_max_chars" in runner_params:
                    kwargs["capture_max_chars"] = settings.cli_result_max_chars
                result = runner.run(
                    command_list,
                    cwd=cwd,
                    on_output=on_output,
                    **kwargs,
                )
            result.metadata.update({"agent_command": agent_command, "cwd": str(cwd), "run_id": run_id, "raw_log_path": str(raw_log_path)})
            if use_codex_sdk and result.metadata.get("codex_thread_id"):
                result.metadata["session_id"] = result.metadata["codex_thread_id"]
            return result
        finally:
            raw_log_handle.close()
            self._flush_cli_output(iteration_id)
            if not self._is_iteration_gone(iteration_id):
                if self._is_real_cli(state.get("mode")):
                    publish_cli_display_events(cli_presenter.flush(node=str(current_node)))
                self._publish_snapshot(iteration_id)


    def _cli_display_event(self, iteration_id: str, event: CliDisplayEvent) -> None:
        if event.phase in self._PERSISTED_CLI_PHASES or self._should_persist_preview_event(event):
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


    @staticmethod
    def _should_persist_preview_event(event: CliDisplayEvent) -> bool:
        if event.provider != "codex":
            return False
        return event.phase == "text" and event.status == "completed"


    @staticmethod
    def _provider_from_run_result(run_result: CLIResult) -> str:
        agent_command = run_result.metadata.get("agent_command")
        return agent_command.provider if isinstance(agent_command, AgentCommand) else "claude"

    @staticmethod
    def _cli_failure_action_hint(run_result: CLIResult, *, context: str = "") -> str:
        provider = PipelineRuntimeMixin._provider_from_run_result(run_result)
        if provider == "codex":
            base = "查看运行日志，确认 Codex SDK 已安装、认证并能连接运行时；最终输出需包含 <specforge_artifact> JSON artifact。"
        else:
            base = "查看运行日志，确认 Claude Code CLI 可用；最终输出需包含 <specforge_artifact> JSON artifact。"
        if context:
            return f"{base} {context}"
        return base

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
            "artifact.invalid": "查看对应 agent 的原始日志，确认最终回复包含合法 <specforge_artifact> JSON，并满足当前阶段 schema。",
            "artifact.self_max_retries": "查看最后一次产物错误和原始日志，必要时人工修正 prompt 或产物 schema。",
            "ui_spec.invalid": "查看对应 agent 的原始日志，确认 UI 产物文件是合法 JSON，并满足 UI spec contract。",
            "test_integrity.failed": "检查受保护测试是否被修改；必要时重新生成规划和测试基线。",
            "planning_integrity.failed": "检查 PRD、testing_plan 与 context manifests 是否被非规划节点修改；必要时回到 Test Planner 重新生成 baseline。",
            "prd_planner.failed": "检查 CLI Provider（Claude Code 或 Codex SDK）、模型配置和 API 凭据。",
            "coder.failed": "检查 CLI Provider（Claude Code 或 Codex SDK）、工作区权限和失败日志。",
            "code_tester.max_retries": "查看最后一次验证失败说明，必要时人工调整需求或实现。",
            "clarification.max_retries": "补充需求细节或约束后重新启动迭代。",
            "planner_verify.max_retries": "检查验证报告结构，确保包含测试摘要和通过信息。",
            "job.failed": "查看后端日志，确认后台 worker 和 LangGraph checkpoint 状态。",
        }
        return hints.get(event_type, "查看事件流和运行日志，处理阻断后重新创建或重试迭代。")
