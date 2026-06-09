from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import re
from queue import Empty, Queue
from types import SimpleNamespace
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .cli_runner import BoundedTextBuffer, CLIResult
from .providers import AgentCommand


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CodexSdkRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, Any] = {}

    def run_agent(
        self,
        command: AgentCommand,
        cwd: Optional[Path] = None,
        on_output: Optional[Callable[[str, str], None]] = None,
        *,
        iteration_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        capture_max_chars: Optional[int] = None,
    ) -> CLIResult:
        started_at = _utcnow()
        stdout_buffer = BoundedTextBuffer(capture_max_chars)
        stderr_buffer = BoundedTextBuffer(capture_max_chars)

        def emit(payload: dict[str, Any]) -> None:
            line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            stdout_buffer.append(line)
            if on_output:
                on_output("stdout", line)

        try:
            from openai_codex import ApprovalMode, Codex, Sandbox
        except Exception as exc:
            return CLIResult(
                command=command.command,
                returncode=127,
                stdout=stdout_buffer.text,
                stderr=f"openai-codex SDK unavailable: {exc}",
                started_at=started_at,
                finished_at=_utcnow(),
                stdout_byte_count=stdout_buffer.byte_count,
                stderr_byte_count=0,
            )

        try:
            with Codex() as codex:
                thread = self._thread(codex, command, cwd=cwd, ApprovalMode=ApprovalMode, Sandbox=Sandbox)
                emit({"type": "thread.started", "thread_id": thread.id, "source": "codex-sdk"})
                turn = thread.turn(
                    command.prompt_bundle.user_prompt,
                    approval_mode=ApprovalMode.auto_review,
                    cwd=str(cwd) if cwd else None,
                    sandbox=Sandbox.full_access,
                )
                if iteration_id:
                    with self._lock:
                        self._active[iteration_id] = turn
                emit({"type": "turn.started", "thread_id": thread.id, "turn_id": getattr(turn, "id", None), "source": "codex-sdk"})
                result = self._consume_stream(
                    turn,
                    emit=emit,
                    deadline=time.monotonic() + timeout_seconds if timeout_seconds else None,
                    idle_timeout_seconds=idle_timeout_seconds,
                )
                status = str(_value(getattr(result, "status", None)) or "")
                failed = status.lower() in {"failed", "error", "cancelled", "canceled"}
                error = getattr(result, "error", None)
                artifact = _extract_structured_payload(result)
                if artifact is not None:
                    emit(
                        {
                            "type": "result",
                            "thread_id": thread.id,
                            "turn_id": getattr(result, "id", None),
                            "structured_output": artifact,
                            "source": "codex-sdk",
                        }
                    )
                emit(
                    {
                        "type": "turn.completed",
                        "thread_id": thread.id,
                        "turn_id": getattr(result, "id", None),
                        "status": status or None,
                        "duration_ms": getattr(result, "duration_ms", None),
                        "source": "codex-sdk",
                    }
                )
                stderr = _payload_error(error) if error else ""
                return CLIResult(
                    command=command.command,
                    returncode=1 if failed else 0,
                    stdout=stdout_buffer.text,
                    stderr=stderr or stderr_buffer.text,
                    started_at=started_at,
                    finished_at=_utcnow(),
                    metadata={
                        "codex_thread_id": thread.id,
                        "codex_turn_id": getattr(result, "id", None),
                        "stdout_truncated": stdout_buffer.truncated,
                        "stderr_truncated": stderr_buffer.truncated,
                    },
                    stdout_byte_count=stdout_buffer.byte_count,
                    stderr_byte_count=stderr_buffer.byte_count,
                )
        except TimeoutError as exc:
            stderr_buffer.append(str(exc))
            return CLIResult(
                command=command.command,
                returncode=124,
                stdout=stdout_buffer.text,
                stderr=stderr_buffer.text,
                started_at=started_at,
                finished_at=_utcnow(),
                timed_out=True,
                metadata={"stdout_truncated": stdout_buffer.truncated, "stderr_truncated": stderr_buffer.truncated},
                stdout_byte_count=stdout_buffer.byte_count,
                stderr_byte_count=stderr_buffer.byte_count,
            )
        except Exception as exc:
            stderr_buffer.append(str(exc))
            emit({"type": "turn.failed", "error": str(exc), "source": "codex-sdk"})
            return CLIResult(
                command=command.command,
                returncode=1,
                stdout=stdout_buffer.text,
                stderr=stderr_buffer.text,
                started_at=started_at,
                finished_at=_utcnow(),
                metadata={"stdout_truncated": stdout_buffer.truncated, "stderr_truncated": stderr_buffer.truncated},
                stdout_byte_count=stdout_buffer.byte_count,
                stderr_byte_count=stderr_buffer.byte_count,
            )
        finally:
            if iteration_id:
                with self._lock:
                    self._active.pop(iteration_id, None)

    def cancel(self, iteration_id: str) -> bool:
        with self._lock:
            turn = self._active.get(iteration_id)
        if turn is None:
            return False
        try:
            turn.interrupt()
            return True
        except Exception:
            return False

    def cancel_all(self) -> list[str]:
        with self._lock:
            active = dict(self._active)
        cancelled: list[str] = []
        for iteration_id, turn in active.items():
            try:
                turn.interrupt()
                cancelled.append(iteration_id)
            except Exception:
                pass
        return cancelled

    def cleanup_registry_processes(self) -> list[str]:
        return []

    def _thread(self, codex: Any, command: AgentCommand, *, cwd: Optional[Path], ApprovalMode: Any, Sandbox: Any) -> Any:
        if command.session_mode == "continue" and command.session_id:
            return codex.thread_resume(
                command.session_id,
                approval_mode=ApprovalMode.auto_review,
                cwd=str(cwd) if cwd else None,
                sandbox=Sandbox.full_access,
            )
        return codex.thread_start(
            approval_mode=ApprovalMode.auto_review,
            cwd=str(cwd) if cwd else None,
            sandbox=Sandbox.full_access,
        )

    def _consume_stream(
        self,
        turn: Any,
        *,
        emit: Callable[[dict[str, Any]], None],
        deadline: float | None,
        idle_timeout_seconds: int | None,
    ) -> Any:
        items: list[Any] = []
        usage: Any = None
        completed_turn: Any = None
        stream_queue: Queue[Any] = Queue()
        sentinel = object()

        def consume() -> None:
            try:
                for notification in turn.stream():
                    stream_queue.put(notification)
            except BaseException as exc:  # pragma: no cover - defensive around SDK stream internals
                stream_queue.put(exc)
            finally:
                stream_queue.put(sentinel)

        threading.Thread(target=consume, name="specforge-codex-sdk-stream", daemon=True).start()
        idle_deadline = time.monotonic() + idle_timeout_seconds if idle_timeout_seconds else None
        while True:
            try:
                notification = stream_queue.get(timeout=0.25)
            except Empty:
                if deadline is not None and time.monotonic() > deadline:
                    with _ignore_errors():
                        turn.interrupt()
                    raise TimeoutError("Codex SDK turn timed out")
                if idle_deadline is not None and time.monotonic() > idle_deadline:
                    with _ignore_errors():
                        turn.interrupt()
                    raise TimeoutError(f"Codex SDK turn idle timed out after {idle_timeout_seconds}s")
                continue
            if notification is sentinel:
                break
            if isinstance(notification, BaseException):
                raise notification
            if deadline is not None and time.monotonic() > deadline:
                with _ignore_errors():
                    turn.interrupt()
                raise TimeoutError("Codex SDK turn timed out")
            if idle_timeout_seconds:
                idle_deadline = time.monotonic() + idle_timeout_seconds
            payload = _notification_payload(notification)
            item = _payload_item(payload)
            if item is not None:
                items.append(item)
            maybe_usage = _payload_usage(payload)
            if maybe_usage is not None:
                usage = maybe_usage
            maybe_turn = _payload_turn(payload)
            if maybe_turn is not None:
                completed_turn = maybe_turn
            event = _synthetic_event(payload)
            if event is not None:
                emit(event)
        return SimpleNamespace(
            id=_dict_value(completed_turn, "id") or getattr(turn, "id", None),
            status=_dict_value(completed_turn, "status"),
            error=_dict_value(completed_turn, "error"),
            started_at=_dict_value(completed_turn, "started_at", "startedAt"),
            completed_at=_dict_value(completed_turn, "completed_at", "completedAt"),
            duration_ms=_dict_value(completed_turn, "duration_ms", "durationMs"),
            final_response=_final_response_from_items(items),
            items=items,
            usage=usage,
        )


class _ignore_errors:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return True


def _notification_payload(notification: Any) -> Any:
    payload = getattr(notification, "payload", notification)
    plain = _plain(payload)
    if isinstance(plain, dict):
        plain.setdefault("_class", type(payload).__name__)
        method = getattr(notification, "method", None)
        if method:
            plain.setdefault("method", str(method))
    return plain


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if is_dataclass(value):
        return _plain(asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return _plain(value.model_dump(mode="json"))
        except TypeError:
            return _plain(value.model_dump())
    if hasattr(value, "__dict__"):
        return {str(key): _plain(child) for key, child in vars(value).items() if not key.startswith("_")}
    return str(value)


def _synthetic_event(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    body = _event_body(payload)
    root = body.get("root") if isinstance(body.get("root"), dict) else None
    method = str(payload.get("method") or "").strip()
    method_event = _event_from_sdk_method(method, payload)
    if method_event is not None:
        return method_event
    event_type = _normalize_event_type(
        str(body.get("type") or (root or {}).get("type") or ""),
        str(payload.get("_class") or ""),
    )
    if event_type:
        event = dict(body)
        event["type"] = event_type
        if method:
            event["method"] = method
        if "_class" in payload:
            event["_class"] = payload["_class"]
        item = _payload_item(event)
        if item is not None:
            event["item"] = _unwrap_root(item)
        turn = _payload_turn(event)
        if turn is not None:
            event["turn"] = _unwrap_root(turn)
        event.setdefault("source", "codex-sdk")
        return event
    if "item" in body:
        return {"type": "item.completed", "item": _unwrap_root(body["item"]), "source": "codex-sdk", "raw": payload}
    if "turn" in body:
        return {"type": "turn.completed", "turn": _unwrap_root(body["turn"]), "source": "codex-sdk", "raw": payload}
    if root and "item" in root:
        return {"type": "item.completed", "item": _unwrap_root(root["item"]), "source": "codex-sdk", "raw": payload}
    return {"type": "item.updated", "item": _unwrap_root(body), "source": "codex-sdk", "raw": payload}


def _event_from_sdk_method(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not method:
        return None
    body = _event_body(payload)
    event = dict(body)
    event["method"] = method
    event["sdk_method"] = method
    if "_class" in payload:
        event["_class"] = payload["_class"]
    event.setdefault("source", "codex-sdk")
    if method == "thread/started":
        event["type"] = "thread.started"
        return event
    if method == "turn/started":
        event["type"] = "turn.started"
        turn = _payload_turn(event)
        if turn is not None:
            event["turn"] = _unwrap_root(turn)
        return event
    if method == "turn/completed":
        event["type"] = "turn.completed"
        turn = _payload_turn(event)
        if turn is not None:
            event["turn"] = _unwrap_root(turn)
        return event
    if method == "error":
        event["type"] = "turn.failed"
        return event
    if method == "item/started":
        event["type"] = "item.started"
        item = _payload_item(event)
        if item is not None:
            event["item"] = _unwrap_root(item)
        return event
    if method == "item/completed":
        event["type"] = "item.completed"
        item = _payload_item(event)
        if item is not None:
            event["item"] = _unwrap_root(item)
        return event
    if method in _SDK_ITEM_DELTA_TYPES:
        event["type"] = "item.updated"
        event["item"] = _item_from_sdk_delta(method, event)
        return event
    if method == "item/fileChange/patchUpdated":
        event["type"] = "item.updated"
        event["item"] = {
            "type": "fileChange",
            "id": event.get("itemId") or event.get("item_id"),
            "changes": event.get("changes"),
            "status": "inProgress",
        }
        return event
    if method in {"turn/plan/updated", "turn/diff/updated"}:
        event["type"] = "item.updated"
        event["item"] = {
            "type": "plan" if method == "turn/plan/updated" else "fileChange",
            "text": event.get("plan") or event.get("diff") or event.get("delta") or "",
        }
        return event
    if method.startswith("item/") and method.endswith("/started"):
        event["type"] = "item.started"
        return event
    if method.startswith("item/") and method.endswith("/completed"):
        event["type"] = "item.completed"
        return event
    if method.startswith("item/"):
        event["type"] = "item.updated"
        event.setdefault("item", _unwrap_root(payload))
        return event
    return None


_SDK_ITEM_DELTA_TYPES = {
    "item/agentMessage/delta",
    "item/plan/delta",
    "item/commandExecution/outputDelta",
    "item/commandExecution/terminalInteraction",
    "item/fileChange/outputDelta",
    "item/mcpToolCall/progress",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/summaryPartAdded",
    "item/reasoning/textDelta",
}


def _item_from_sdk_delta(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = payload.get("itemId") or payload.get("item_id")
    if method == "item/agentMessage/delta":
        return {"type": "agentMessage", "id": item_id, "text": payload.get("delta") or ""}
    if method == "item/plan/delta":
        return {"type": "plan", "id": item_id, "text": payload.get("delta") or ""}
    if method in {"item/commandExecution/outputDelta", "item/commandExecution/terminalInteraction"}:
        return {
            "type": "commandExecution",
            "id": item_id,
            "aggregatedOutput": payload.get("delta") or "",
            "status": "inProgress",
        }
    if method == "item/fileChange/outputDelta":
        return {
            "type": "fileChange",
            "id": item_id,
            "preview": payload.get("delta") or "",
            "status": "inProgress",
        }
    if method == "item/mcpToolCall/progress":
        return {
            "type": "mcpToolCall",
            "id": item_id,
            "message": payload.get("message") or "",
            "status": "inProgress",
        }
    if method in {
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
    }:
        return {
            "type": "reasoning",
            "id": item_id,
            "text": payload.get("delta") or payload.get("text") or "",
            "status": "inProgress",
        }
    return {"id": item_id, "type": method.split("/", 2)[1] if "/" in method else "unknown"}


def _event_body(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params")
    if isinstance(params, dict):
        return params
    return payload


def _unwrap_root(value: Any) -> Any:
    if isinstance(value, dict) and isinstance(value.get("root"), dict):
        return _unwrap_root(value["root"])
    return value


def _normalize_event_type(raw: str, class_name: str = "") -> str:
    value = raw.strip()
    if value:
        value = value.replace("/", ".").replace("_", ".")
        value = re.sub(r"(?<!^)(?=[A-Z])", ".", value).lower()
        value = value.replace("..", ".")
        if value in {"thread.started", "turn.started", "turn.completed", "turn.failed", "item.started", "item.updated", "item.completed"}:
            return value
        if value.endswith(".notification"):
            value = value[: -len(".notification")]
        for prefix in ("thread", "turn", "item"):
            if value.startswith(f"{prefix}."):
                parts = value.split(".")
                for status in ("started", "updated", "completed", "failed"):
                    if status in parts:
                        return f"{prefix}.{status}"
    if class_name:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        name = name.removesuffix("_notification")
        parts = name.split("_")
        for prefix in ("thread", "turn", "item"):
            if prefix in parts:
                for status in ("started", "updated", "completed", "failed"):
                    if status in parts:
                        return f"{prefix}.{status}"
    return ""


def _payload_item(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    item = payload.get("item")
    if item is not None:
        return item
    params = payload.get("params")
    if isinstance(params, dict):
        return _payload_item(params)
    root = payload.get("root")
    if isinstance(root, dict):
        return _payload_item(root)
    return None


def _payload_turn(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    turn = payload.get("turn")
    if turn is not None:
        return turn
    params = payload.get("params")
    if isinstance(params, dict):
        return _payload_turn(params)
    root = payload.get("root")
    if isinstance(root, dict):
        return _payload_turn(root)
    return None


def _payload_error(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        message = error.get("message") or error.get("error")
        if isinstance(message, str):
            return message
        return json.dumps(error, ensure_ascii=False)
    params = payload.get("params")
    if isinstance(params, dict):
        return _payload_error(params)
    root = payload.get("root")
    if isinstance(root, dict):
        return _payload_error(root)
    return ""


def _payload_usage(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("token_usage") or payload.get("tokenUsage") or payload.get("usage")
    if usage is not None:
        return usage
    params = payload.get("params")
    if isinstance(params, dict):
        return _payload_usage(params)
    root = payload.get("root")
    if isinstance(root, dict):
        return _payload_usage(root)
    return None


def _dict_value(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _final_response_from_items(items: list[Any]) -> str | None:
    for item in reversed(items):
        for candidate in _item_text_candidates(_plain(item)):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, (dict, list)):
                encoded = json.dumps(candidate, ensure_ascii=False)
                if encoded:
                    return encoded
    return None


def _extract_structured_payload(result: Any) -> Any:
    for candidate in _result_candidates(result):
        decoded = _decode_jsonish(candidate)
        if decoded is not None:
            return decoded
    return None


def _result_candidates(result: Any) -> list[Any]:
    candidates: list[Any] = []
    final_response = getattr(result, "final_response", None)
    if final_response:
        candidates.append(final_response)
    for item in getattr(result, "items", []) or []:
        plain = _plain(item)
        candidates.extend(_item_text_candidates(plain))
    return candidates


def _item_text_candidates(item: Any) -> list[Any]:
    if not isinstance(item, dict):
        return []
    candidates: list[Any] = []
    for key in ("structured_output", "text", "message", "content"):
        value = item.get(key)
        if value:
            candidates.append(value)
    root = item.get("root")
    if isinstance(root, dict):
        candidates.extend(_item_text_candidates(root))
    return candidates


def _decode_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        if "structured_output" in value:
            return value["structured_output"]
        return value
    if isinstance(value, list):
        texts = [item.get("text", "") for item in value if isinstance(item, dict)]
        value = "".join(texts)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            return None
    if isinstance(payload, dict) and "structured_output" in payload:
        return payload["structured_output"]
    return payload


def _value(value: Any) -> Any:
    return getattr(value, "value", value)
