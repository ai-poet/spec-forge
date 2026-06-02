from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Literal, Optional


Provider = Literal["claude_code", "codex"]
Phase = Literal[
    "session",
    "thinking",
    "text",
    "tool",
    "command",
    "file_change",
    "mcp",
    "todo",
    "hook",
    "retry",
    "result",
    "error",
]
Severity = Literal["info", "success", "warning", "error"]


@dataclass
class CliDisplayEvent:
    provider: Provider
    node: str
    phase: Phase
    title: str
    message: str
    severity: Severity = "info"
    item_id: Optional[str] = None
    status: Optional[str] = None
    command: Optional[str] = None
    paths: list[str] = field(default_factory=list)
    tool: Optional[str] = None
    preview: Optional[str] = None
    raw_event: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        raw_type = str(self.raw_event.get("type") or self.raw_event.get("event") or "")
        parts = [self.provider, self.node, self.phase, raw_type, self.item_id or "", self.status or ""]
        if self.command:
            parts.append(self.command)
        if self.tool:
            parts.append(self.tool)
        return ":".join(parts)

    def payload(self, *, include_raw: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "node": self.node,
            "phase": self.phase,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
        }
        if include_raw:
            payload["raw_event"] = self.raw_event
        if self.item_id:
            payload["item_id"] = self.item_id
        if self.status:
            payload["status"] = self.status
        if self.command:
            payload["command"] = self.command
        if self.paths:
            payload["paths"] = self.paths
        if self.tool:
            payload["tool"] = self.tool
        if self.preview:
            payload["preview"] = self.preview
        return payload


class CliEventPresenter:
    def present_chunk(self, chunk: str, *, node: str) -> list[CliDisplayEvent]:
        events: list[CliDisplayEvent] = []
        for line in [line.strip() for line in chunk.splitlines() if line.strip()]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = self.present(payload, node=node)
            if event:
                events.append(event)
        return events

    def present(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        if self._looks_like_codex(payload):
            return CodexEventPresenter().present(payload, node=node)
        if self._looks_like_claude(payload):
            return ClaudeCodeEventPresenter().present(payload, node=node)
        return None

    def _looks_like_codex(self, payload: dict[str, Any]) -> bool:
        event_type = str(payload.get("type") or payload.get("event") or "")
        return event_type.startswith(("thread.", "turn.", "item.")) or "item" in payload

    def _looks_like_claude(self, payload: dict[str, Any]) -> bool:
        event_type = str(payload.get("type") or "")
        return (
            event_type in {"system", "assistant", "user", "result", "stream_event", "hook"}
            or "stream_event" in payload
            or bool(payload.get("hook_event"))
        )


class ClaudeCodeEventPresenter:
    def present(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        event_type = str(payload.get("type") or "")
        subtype = str(payload.get("subtype") or "")
        if event_type == "hook" or payload.get("hook_event") or subtype.startswith("hook"):
            hook_name = str(payload.get("hook_name") or payload.get("hook_event") or subtype or "hook")
            hook_msg = _compact(payload.get("message") or payload.get("summary") or payload)
            return CliDisplayEvent(
                "claude_code",
                node,
                "hook",
                f"Hook: {hook_name}",
                hook_msg or "Claude Code hook event fired.",
                tool=hook_name,
                raw_event=payload,
            )
        if event_type == "system" and subtype == "init":
            model = str(payload.get("model") or "")
            tools = payload.get("tools")
            tool_count = len(tools) if isinstance(tools, list) else 0
            message = "Claude Code 已启动会话。"
            if model or tool_count:
                message = f"模型: {model or '未知'}，可用工具: {tool_count} 个。"
            return CliDisplayEvent("claude_code", node, "session", "Claude Code 会话已初始化", message, raw_event=payload)
        if event_type == "system" and subtype == "resume":
            model = str(payload.get("model") or "")
            message = "Claude Code 会话已恢复（规划续接）。"
            if model:
                message = f"模型: {model}，会话已恢复（规划续接）。"
            return CliDisplayEvent("claude_code", node, "session", "会话已恢复（规划续接）", message, raw_event=payload)
        if event_type == "system" and subtype == "api_retry":
            attempt = payload.get("attempt") or payload.get("retry_count")
            max_attempts = payload.get("max_attempts") or payload.get("max_retries")
            error = _compact(payload.get("error") or payload.get("message"))
            message = "API 请求正在重试。"
            if attempt or max_attempts:
                message = f"第 {attempt or '?'} / {max_attempts or '?'} 次重试。"
            if error:
                message = f"{message} {error}"
            return CliDisplayEvent("claude_code", node, "retry", "Claude API 请求重试中", message, severity="warning", status="retrying", raw_event=payload)
        if event_type == "stream_event":
            return self._present_stream_event(payload, node=node)
        if event_type == "assistant":
            return self._present_assistant_message(payload, node=node)
        if event_type == "user":
            return self._present_user_message(payload, node=node)
        if event_type == "result":
            if "structured_output" in payload:
                return CliDisplayEvent("claude_code", node, "result", "结构化产物已生成", "Claude Code 已返回可校验 artifact，后端正在落盘。", severity="success", status="completed", raw_event=payload)
            return CliDisplayEvent("claude_code", node, "result", "Claude Code 输出已完成", "CLI 已返回最终结果，后端正在解析。", severity="success", status="completed", raw_event=payload)
        return None

    def _present_stream_event(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        stream_event = payload.get("stream_event") if isinstance(payload.get("stream_event"), dict) else payload
        stream_type = str(stream_event.get("type") or "")
        block_index = stream_event.get("index")
        item_id = str(block_index) if block_index is not None else None
        if stream_type == "content_block_delta":
            delta = stream_event.get("delta") if isinstance(stream_event.get("delta"), dict) else {}
            delta_type = str(delta.get("type") or "")
            if delta_type == "text_delta":
                text = _compact(delta.get("text"))
                return CliDisplayEvent(
                    "claude_code",
                    node,
                    "text",
                    "Claude 正在生成文本",
                    text or "模型正在流式输出内容。",
                    preview=text,
                    item_id=item_id,
                    raw_event=payload,
                )
            if delta_type == "thinking_delta":
                text = _compact(delta.get("thinking") or delta.get("text"))
                return CliDisplayEvent(
                    "claude_code",
                    node,
                    "thinking",
                    "Claude 正在推理",
                    text or "模型正在形成下一步操作。",
                    preview=text,
                    item_id=item_id,
                    raw_event=payload,
                )
        if stream_type == "content_block_start":
            content = stream_event.get("content_block") if isinstance(stream_event.get("content_block"), dict) else {}
            if content.get("type") == "tool_use":
                tool = str(content.get("name") or "tool")
                paths = _tool_input_paths(content.get("input"))
                command = _tool_input_command(content.get("input"), tool)
                return CliDisplayEvent(
                    "claude_code",
                    node,
                    "tool",
                    f"调用工具: {tool}",
                    "Claude Code 正在调用工具。",
                    tool=tool,
                    item_id=str(content.get("id") or ""),
                    paths=paths,
                    command=command,
                    raw_event=payload,
                )
        if stream_type == "message_stop":
            return CliDisplayEvent("claude_code", node, "result", "Claude 消息输出完成", "本轮模型消息已经结束。", severity="success", status="completed", raw_event=payload)
        return None

    def _present_assistant_message(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool = str(block.get("name") or "tool")
                    preview = _compact(block.get("input"))
                    paths = _tool_input_paths(block.get("input"))
                    command = _tool_input_command(block.get("input"), tool)
                    return CliDisplayEvent(
                        "claude_code",
                        node,
                        "tool",
                        f"调用工具: {tool}",
                        preview or "Claude Code 正在调用工具。",
                        tool=tool,
                        item_id=str(block.get("id") or ""),
                        preview=preview,
                        paths=paths,
                        command=command,
                        raw_event=payload,
                    )
                if block.get("type") == "text":
                    text = _compact(block.get("text"))
                    return CliDisplayEvent("claude_code", node, "text", "Claude 输出说明", text or "Claude Code 正在输出文本。", preview=text, raw_event=payload)
        return CliDisplayEvent("claude_code", node, "text", "Claude 正在生成方案", "模型正在输出规划或实现内容。", raw_event=payload)

    def _present_user_message(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    preview = _compact(block.get("content"))
                    return CliDisplayEvent("claude_code", node, "tool", "工具返回结果", preview or "工具结果已返回给 Claude Code。", item_id=str(block.get("tool_use_id") or ""), preview=preview, raw_event=payload)
        return None


class CodexEventPresenter:
    def present(self, payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        msg = payload.get("msg") if isinstance(payload.get("msg"), dict) else {}
        event_type = str(payload.get("type") or payload.get("event") or msg.get("type") or "")
        item = payload.get("item") if isinstance(payload.get("item"), dict) else msg.get("item") if isinstance(msg.get("item"), dict) else {}
        if event_type == "thread.started":
            return CliDisplayEvent("codex", node, "session", "Codex 验证会话已启动", "Tester 已创建独立执行线程。", raw_event=payload)
        if event_type == "turn.started":
            return CliDisplayEvent("codex", node, "thinking", "Codex 回合已开始", "Tester 正在分析任务并准备执行。", raw_event=payload)
        if event_type == "turn.completed":
            return CliDisplayEvent("codex", node, "result", "Codex 回合已完成", "Tester 已完成本轮验证输出。", severity="success", status="completed", raw_event=payload)
        if event_type == "turn.failed":
            return CliDisplayEvent("codex", node, "error", "Codex 回合失败", _compact(payload.get("error")) or "Tester 执行过程中出现失败。", severity="error", status="failed", raw_event=payload)
        if event_type in {"item.started", "item.updated", "item.completed"}:
            return self._present_item(event_type, item, payload, node=node)
        if event_type in {"agent_reasoning", "agent_message"}:
            return self._present_legacy_item(event_type, payload, node=node)
        if event_type == "error":
            return CliDisplayEvent("codex", node, "error", "Codex 输出错误", _compact(payload.get("message") or payload.get("error")) or "Codex CLI 返回错误事件。", severity="error", status="failed", raw_event=payload)
        return None

    def _present_item(self, event_type: str, item: dict[str, Any], payload: dict[str, Any], *, node: str) -> Optional[CliDisplayEvent]:
        item_type = str(item.get("type") or "")
        item_id = str(item.get("id") or item.get("item_id") or "")
        status = "started" if event_type == "item.started" else "completed" if event_type == "item.completed" else "updated"
        if item_type == "command_execution":
            command = _command_text(item)
            exit_code = item.get("exit_code")
            item_status = str(item.get("status") or status)
            failed = item_status in {"failed", "error", "cancelled"} or (isinstance(exit_code, int) and exit_code != 0)
            if status == "started":
                return CliDisplayEvent("codex", node, "command", "执行命令", command or "Codex 正在执行命令。", item_id=item_id, status=status, command=command, raw_event=payload)
            title = "命令失败" if failed else "命令完成"
            message = command or "命令执行结束。"
            if exit_code is not None:
                message = f"{message} exit code: {exit_code}"
            return CliDisplayEvent("codex", node, "command", title, message, severity="error" if failed else "success", item_id=item_id, status=item_status, command=command, raw_event=payload)
        if item_type == "file_change":
            paths = _file_change_paths(item)
            action = str(item.get("action") or item.get("operation") or "应用")
            return CliDisplayEvent("codex", node, "file_change", "应用文件变更", f"{action}: {', '.join(paths) if paths else '文件变更已应用。'}", severity="success" if status == "completed" else "info", item_id=item_id, status=status, paths=paths, raw_event=payload)
        if item_type == "mcp_tool_call":
            tool = _mcp_tool_name(item)
            failed = str(item.get("status") or "") in {"failed", "error"}
            title = "MCP 调用失败" if failed else "调用 MCP 工具" if status == "started" else "MCP 调用完成"
            return CliDisplayEvent("codex", node, "mcp", title, tool or "Codex 正在调用 MCP 工具。", severity="error" if failed else "success" if status == "completed" else "info", item_id=item_id, status=status, tool=tool, raw_event=payload)
        if item_type == "todo_list":
            preview = _todo_preview(item)
            return CliDisplayEvent("codex", node, "todo", "更新任务清单", preview or "Codex 已更新执行清单。", item_id=item_id, status=status, preview=preview, raw_event=payload)
        if item_type in {"reasoning", "agent_reasoning"}:
            preview = _compact(item.get("text") or item.get("summary"))
            return CliDisplayEvent("codex", node, "thinking", "Codex 正在推理", preview or "Tester 正在形成验证判断。", item_id=item_id, status=status, preview=preview, raw_event=payload)
        if item_type == "agent_message":
            preview = _compact(item.get("text"))
            return CliDisplayEvent("codex", node, "text", "Codex 输出验证结论", preview or "Tester 正在输出最终报告内容。", item_id=item_id, status=status, preview=preview, raw_event=payload)
        if item_type == "error":
            return CliDisplayEvent("codex", node, "error", "Codex item 错误", _compact(item.get("message") or item.get("error")) or "Codex CLI 返回错误 item。", severity="error", item_id=item_id, status="failed", raw_event=payload)
        return CliDisplayEvent("codex", node, "thinking", f"Codex {item_type or '步骤'}", "原始 CLI 事件已保存，可在详情里查看。", item_id=item_id, status=status, raw_event=payload)

    def _present_legacy_item(self, event_type: str, payload: dict[str, Any], *, node: str) -> CliDisplayEvent:
        if event_type == "agent_reasoning":
            text = _compact(payload.get("text"))
            return CliDisplayEvent("codex", node, "thinking", "Codex 正在推理", text or "Tester 正在形成验证判断。", preview=text, raw_event=payload)
        text = _compact(payload.get("text") or payload.get("message"))
        return CliDisplayEvent("codex", node, "text", "Codex 输出验证结论", text or "Tester 正在输出最终报告内容。", preview=text, raw_event=payload)


def _tool_input_paths(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    paths: list[str] = []
    for key in ("file_path", "filePath", "path", "notebook_path"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            paths.append(raw.strip())
    for key in ("paths", "files"):
        raw = value.get(key)
        if isinstance(raw, list):
            paths.extend(str(item) for item in raw if str(item).strip())
    return sorted(set(paths))


def _tool_input_command(value: Any, tool: str) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    command = value.get("command") or value.get("cmd")
    if isinstance(command, list):
        return " ".join(map(str, command))
    if isinstance(command, str) and command.strip():
        return command.strip()
    if tool.lower() in {"bash", "shell"} and isinstance(value.get("command"), str):
        return str(value["command"])
    return None


def _compact(value: Any, *, limit: int = 360) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    if len(text) > limit:
        return f"{text[:limit - 1]}…"
    return text


def _command_text(item: dict[str, Any]) -> Optional[str]:
    command = item.get("command") or item.get("cmd")
    if isinstance(command, list):
        return " ".join(map(str, command))
    if isinstance(command, str):
        return command
    return None


def _file_change_paths(item: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("path", "file", "file_path"):
        value = item.get(key)
        if isinstance(value, str):
            paths.append(value)
    raw_paths = item.get("paths")
    if isinstance(raw_paths, list):
        paths.extend(str(path) for path in raw_paths)
    changes = item.get("changes")
    if isinstance(changes, list):
        for change in changes:
            if isinstance(change, dict):
                value = change.get("path") or change.get("file") or change.get("file_path")
                if isinstance(value, str):
                    paths.append(value)
    return sorted(set(paths))


def _mcp_tool_name(item: dict[str, Any]) -> str:
    server = item.get("server") or item.get("server_name")
    tool = item.get("tool") or item.get("tool_name") or item.get("name")
    if server and tool:
        return f"{server}/{tool}"
    return str(tool or server or "")


def _todo_preview(item: dict[str, Any]) -> str:
    todos = item.get("todos") or item.get("items")
    if not isinstance(todos, list):
        return ""
    lines: list[str] = []
    for todo in todos[:8]:
        if isinstance(todo, dict):
            status = str(todo.get("status") or "")
            text = str(todo.get("text") or todo.get("content") or todo.get("title") or "")
            prefix = "完成" if status in {"completed", "done"} else "进行中" if status in {"in_progress", "active"} else "待办"
            if text:
                lines.append(f"{prefix}: {text}")
    return "\n".join(lines)
