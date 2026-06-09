from __future__ import annotations

import json

from specforge.agents.cli_event_presenter import CliEventPresenter


def present(payload):
    event = CliEventPresenter().present(payload, node="code_tester")
    assert event is not None
    return event


def json_line(payload):
    return json.dumps(payload, ensure_ascii=False) + "\n"


def test_claude_hook_event_is_displayed():
    hook = present({"type": "hook", "hook_name": "SessionStart", "message": "started"})
    assert hook.phase == "hook"
    assert "SessionStart" in hook.title


def test_claude_init_and_api_retry_are_display_events():
    init = present({"type": "system", "subtype": "init", "model": "sonnet", "tools": ["Read", "Edit"]})
    assert init.provider == "claude_code"
    assert init.phase == "session"
    assert "sonnet" in init.message

    retry = present({"type": "system", "subtype": "api_retry", "attempt": 2, "max_attempts": 5, "error": "rate limited"})
    assert retry.phase == "retry"
    assert retry.severity == "warning"
    assert "rate limited" in retry.message


def test_claude_stream_delta_tool_use_tool_result_and_structured_output():
    text = present({"type": "stream_event", "stream_event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}})
    assert text.phase == "text"
    assert text.preview == "hello"

    tool = present({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "pytest"}}]}})
    assert tool.phase == "tool"
    assert tool.tool == "Bash"

    result = present({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tool_1", "content": "passed"}]}})
    assert result.title == "工具返回结果"
    assert result.preview == "passed"

    structured = present({"type": "result", "structured_output": {"ok": True}})
    assert structured.phase == "result"
    assert structured.severity == "success"
    assert structured.provider == "claude_code"


def test_codex_sdk_result_uses_codex_provider_copy():
    result = present({"type": "result", "structured_output": {"ok": True}, "source": "codex-sdk"})

    assert result.provider == "codex"
    assert result.phase == "result"
    assert "Codex SDK" in result.message
    assert "Claude" not in result.message


def test_codex_lifecycle_command_file_mcp_todo_agent_and_failure_events():
    thread = present({"type": "thread.started"})
    assert thread.provider == "codex"
    assert thread.phase == "session"

    command_start = present({"type": "item.started", "item": {"type": "command_execution", "id": "cmd_1", "command": ["pytest", "-q"]}})
    assert command_start.phase == "command"
    assert command_start.command == "pytest -q"

    command_done = present({"type": "item.completed", "item": {"type": "command_execution", "id": "cmd_1", "command": ["pytest", "-q"], "exit_code": 1}})
    assert command_done.severity == "error"
    assert "exit code: 1" in command_done.message

    file_change = present({"type": "item.completed", "item": {"type": "file_change", "action": "update", "paths": ["src/app.py"]}})
    assert file_change.phase == "file_change"
    assert file_change.paths == ["src/app.py"]

    mcp = present({"type": "item.started", "item": {"type": "mcp_tool_call", "server": "cua", "tool": "click"}})
    assert mcp.phase == "mcp"
    assert mcp.tool == "cua/click"

    todo = present({"type": "item.updated", "item": {"type": "todo_list", "todos": [{"status": "in_progress", "text": "run tests"}]}})
    assert todo.phase == "todo"
    assert "run tests" in (todo.preview or "")

    agent = present({"type": "item.completed", "item": {"type": "agent_message", "text": "all good"}})
    assert agent.phase == "text"
    assert agent.preview == "all good"

    failed = present({"type": "turn.failed", "error": "boom"})
    assert failed.phase == "error"
    assert failed.severity == "error"


def test_codex_sdk_camel_case_items_and_delta_events_are_displayed():
    text_delta = present(
        {
            "type": "item.updated",
            "sdk_method": "item/agentMessage/delta",
            "item": {"type": "agentMessage", "id": "msg_1", "text": "hello"},
        }
    )
    assert text_delta.phase == "text"
    assert text_delta.preview == "hello"
    assert text_delta.status == "updated"

    command_done = present(
        {
            "type": "item.completed",
            "item": {
                "type": "commandExecution",
                "id": "cmd_1",
                "command": "pytest -q",
                "exitCode": 0,
                "status": "completed",
            },
        }
    )
    assert command_done.phase == "command"
    assert command_done.severity == "success"
    assert "exit code: 0" in command_done.message

    mcp_progress = present(
        {
            "type": "item.updated",
            "sdk_method": "item/mcpToolCall/progress",
            "item": {
                "type": "mcpToolCall",
                "id": "mcp_1",
                "server": "docs",
                "tool": "search",
                "message": "searching",
                "status": "inProgress",
            },
        }
    )
    assert mcp_progress.phase == "mcp"
    assert mcp_progress.status == "in_progress"
    assert mcp_progress.preview == "searching"


def test_codex_agent_message_text_is_extracted_from_nested_content():
    nested_message = present(
        {
            "type": "item.completed",
            "item": {
                "type": "agentMessage",
                "id": "msg_1",
                "content": [{"type": "output_text", "text": "visible final text"}],
            },
        }
    )

    assert nested_message.phase == "text"
    assert nested_message.status == "completed"
    assert nested_message.preview == "visible final text"


def test_codex_text_deltas_flush_before_next_non_text_json():
    presenter = CliEventPresenter()
    events = presenter.present_chunk(
        "".join(
            [
                json_line(
                    {
                        "type": "item.updated",
                        "sdk_method": "item/agentMessage/delta",
                        "item": {"type": "agentMessage", "id": "msg_1", "text": "hel"},
                    }
                ),
                json_line(
                    {
                        "type": "item.updated",
                        "sdk_method": "item/agentMessage/delta",
                        "item": {"type": "agentMessage", "id": "msg_1", "text": "lo"},
                    }
                ),
                json_line(
                    {
                        "type": "item.started",
                        "item": {"type": "commandExecution", "id": "cmd_1", "command": "pytest -q"},
                    }
                ),
            ]
        ),
        node="code_tester",
    )

    assert [event.phase for event in events] == ["text", "command"]
    assert events[0].preview == "hello"
    assert events[0].message == "hello"
    assert events[0].status == "completed"
    assert events[1].command == "pytest -q"


def test_codex_text_deltas_merge_across_chunks():
    presenter = CliEventPresenter()

    assert (
        presenter.present_chunk(
            json_line(
                {
                    "type": "item.updated",
                    "sdk_method": "item/agentMessage/delta",
                    "item": {"type": "agentMessage", "id": "msg_1", "text": "hel"},
                }
            ),
            node="code_tester",
        )
        == []
    )
    assert (
        presenter.present_chunk(
            json_line(
                {
                    "type": "item.updated",
                    "sdk_method": "item/agentMessage/delta",
                    "item": {"type": "agentMessage", "id": "msg_1", "text": "lo"},
                }
            ),
            node="code_tester",
        )
        == []
    )

    events = presenter.present_chunk(json_line({"type": "turn.completed", "source": "codex-sdk"}), node="code_tester")

    assert [event.phase for event in events] == ["text", "result"]
    assert events[0].preview == "hello"
    assert events[0].status == "completed"


def test_codex_completed_agent_message_replaces_delta_buffer():
    presenter = CliEventPresenter()
    presenter.present_chunk(
        json_line(
            {
                "type": "item.updated",
                "sdk_method": "item/agentMessage/delta",
                "item": {"type": "agentMessage", "id": "msg_1", "text": "partial"},
            }
        ),
        node="code_tester",
    )
    presenter.present_chunk(
        json_line(
            {
                "type": "item.completed",
                "item": {"type": "agentMessage", "id": "msg_1", "text": "final text"},
            }
        ),
        node="code_tester",
    )

    events = presenter.present_chunk(json_line({"type": "turn.completed", "source": "codex-sdk"}), node="code_tester")

    assert [event.phase for event in events] == ["text", "result"]
    assert events[0].preview == "final text"
    assert "partialfinal" not in events[0].preview


def test_codex_text_flush_returns_pending_tail():
    presenter = CliEventPresenter()
    presenter.present_chunk(
        json_line(
            {
                "type": "item.updated",
                "sdk_method": "item/agentMessage/delta",
                "item": {"type": "agentMessage", "id": "msg_1", "text": "tail"},
            }
        ),
        node="code_tester",
    )

    events = presenter.flush(node="code_tester")

    assert len(events) == 1
    assert events[0].phase == "text"
    assert events[0].preview == "tail"
    assert events[0].status == "completed"
    assert presenter.flush(node="code_tester") == []
