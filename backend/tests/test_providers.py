from __future__ import annotations

from pathlib import Path

from specforge.agents.providers import (
    PromptBundle,
    WorkerRef,
    build_agent_command,
    extract_session_ref,
    validate_worker_ref,
    worker_ref_from_result,
)


def test_build_agent_command_wraps_prompt_bundle():
    command = build_agent_command(
        provider="claude",
        stage="coder",
        prompt="do the work",
        schema_inline='{"type":"object"}',
        schema_file=Path("/tmp/coder.schema.json"),
    )

    assert command.command[0] == "claude"
    assert command.provider == "claude"
    assert command.stage == "coder"
    assert command.prompt_bundle.metadata["stage"] == "coder"
    assert command.prompt_bundle.prompt_hash
    assert command.public_command().endswith("[prompt omitted]")


def test_prompt_bundle_hash_is_stable_and_in_payload():
    bundle = PromptBundle(
        system_prompt="system",
        user_prompt="user",
        output_schema="{}",
        metadata={"stage": "test"},
    )

    assert bundle.prompt_hash == PromptBundle(
        system_prompt="system",
        user_prompt="user",
        output_schema="{}",
        metadata={"stage": "test"},
    ).prompt_hash
    assert bundle.payload()["prompt_hash"] == bundle.prompt_hash


def test_extract_claude_session_ref_from_stream_json():
    ref = extract_session_ref("claude", stdout='{"type":"system","subtype":"init","session_id":"s-1"}\n')
    assert ref == {"sessionId": "s-1"}


def test_extract_codex_thread_ref_from_json_events():
    ref = extract_session_ref("codex", stdout='{"type":"thread.started","thread_id":"t-1"}\n')
    assert ref == {"threadId": "t-1"}


def test_worker_ref_from_result_prefers_command_session():
    command = build_agent_command(
        provider="claude",
        stage="prd_planner",
        prompt="plan",
        schema_inline="{}",
        schema_file=Path("/tmp/schema.json"),
        session_id="planned-session",
        resume=True,
    )

    worker_ref = worker_ref_from_result(command=command, stdout="", stderr="", cwd=Path("/repo"))
    payload = worker_ref.payload()

    assert payload["mode"] == "continue"
    assert payload["supportsContinueSession"] is True
    assert payload["continueRef"]["sessionId"] == "planned-session"
    assert validate_worker_ref(payload)


def test_validate_worker_ref_rejects_bad_payload():
    assert not validate_worker_ref({})
    assert not validate_worker_ref(
        WorkerRef(
            provider="claude",
            mode="new",
            supports_open_session=True,
            supports_continue_session=True,
        ).payload()
        | {"mode": "reuse"}
    )


def test_run_observability_files_and_log_pagination(tmp_path):
    from specforge.agents.cli_runner import CLIResult
    from specforge.pipeline import LangGraphPipeline
    from specforge.storage.db import Database

    db = Database(tmp_path / "db.sqlite3")
    db.init()
    iteration_id = db.create_iteration(project_name="obs", goal="observe", mode="dry-run", test_command=None)
    pipeline = LangGraphPipeline(db=db, runner=__import__("specforge.agents.cli_runner", fromlist=["DryRunRunner"]).DryRunRunner())
    command = build_agent_command(
        provider="claude",
        stage="coder",
        prompt="hello",
        schema_inline="{}",
        schema_file=tmp_path / "schema.json",
        session_id="session-1",
    )
    result = CLIResult(
        command=command.command,
        returncode=0,
        stdout='{"type":"system","session_id":"session-2"}\nline two',
        stderr="warn",
        metadata={"agent_command": command, "cwd": str(tmp_path)},
    )

    run_id = pipeline._record_run(iteration_id, "coder", result)
    page = pipeline.run_logs_page(iteration_id, run_id, offset=0, limit=2)
    prompt = pipeline.run_prompt_bundle(iteration_id, run_id)
    worker_ref = pipeline.run_worker_ref(iteration_id, run_id)
    run = db.list_runs(iteration_id)[0]

    assert page["total"] == 3
    assert page["has_more"] is True
    assert prompt["prompt_hash"] == command.prompt_bundle.prompt_hash
    assert worker_ref["continueRef"]["sessionId"] == "session-1"
    assert run["raw_log_path"]
    assert run["prompt_path"]
    assert run["worker_ref_path"]


def test_iteration_log_summary_export_compacts_large_raw_logs(tmp_path):
    from specforge.pipeline import LangGraphPipeline
    from specforge.storage.db import Database

    db = Database(tmp_path / "db.sqlite3")
    db.init()
    iteration_id = db.create_iteration(project_name="summary", goal="compact logs", mode="dry-run", test_command=None)
    pipeline = LangGraphPipeline(db=db, runner=__import__("specforge.agents.cli_runner", fromlist=["DryRunRunner"]).DryRunRunner())
    raw_log_path = tmp_path / "raw.jsonl"
    long_text = "x" * 1305
    with raw_log_path.open("w", encoding="utf-8") as handle:
        for index in range(1, 151):
            if index == 10:
                text = long_text
            elif index == 40:
                text = "operation failed with error"
            else:
                text = f"stdout line {index}"
            handle.write(f'{{"stream":"stdout","line":{index},"node":"coder","text":"{text}","created_at":"2026-01-01T00:00:00Z"}}\n')
        for index in range(1, 91):
            handle.write(f'{{"stream":"stderr","line":{index},"node":"coder","text":"stderr diagnostic {index}","created_at":"2026-01-01T00:00:00Z"}}\n')
    db.add_run(
        iteration_id,
        run_id="run_large",
        node="coder",
        status="failed",
        command="claude -p",
        stdout="preview only",
        stderr="preview error",
        exit_code=1,
        stdout_bytes=2048,
        stderr_bytes=1024,
        provider="claude",
        prompt_hash="hash-1",
        raw_log_path=str(raw_log_path),
        timed_out=True,
    )

    payload = pipeline.export_iteration_logs(iteration_id, mode="summary")
    run = payload["runs"][0]
    log_summary = run["logs"]["summary"]

    assert payload["mode"] == "summary"
    assert payload["summary"] == {
        "run_count": 1,
        "failed_run_count": 1,
        "stdout_bytes": 2048,
        "stderr_bytes": 1024,
        "has_truncated": True,
    }
    assert run["run_id"] == "run_large"
    assert run["timed_out"] is True
    assert run["prompt_hash"] == "hash-1"
    assert "items" not in run["logs"]
    assert log_summary["items_total"] == 240
    assert len(log_summary["head"]) == 20
    assert len(log_summary["tail"]) == 80
    assert len(log_summary["diagnostics"]) == 80
    assert log_summary["diagnostics_truncated"] is True
    assert log_summary["text_truncated"] is True
    assert log_summary["omitted_middle_count"] == 140
    assert all("stdout line 25" not in section_item["text"] for section in ("head", "tail", "diagnostics") for section_item in log_summary[section])
    assert any(item["text"].startswith("operation failed") for item in log_summary["diagnostics"])
    assert any(item.get("text_truncated") for item in log_summary["head"] + log_summary["tail"] + log_summary["diagnostics"])


def test_worker_ref_from_result_prefers_codex_sdk_thread_id(tmp_path):
    from specforge.agents.cli_runner import CLIResult
    from specforge.pipeline import LangGraphPipeline
    from specforge.storage.db import Database

    db = Database(tmp_path / "db.sqlite3")
    db.init()
    iteration_id = db.create_iteration(project_name="obs", goal="observe", mode="dry-run", test_command=None)
    pipeline = LangGraphPipeline(db=db, runner=__import__("specforge.agents.cli_runner", fromlist=["DryRunRunner"]).DryRunRunner())
    command = build_agent_command(
        provider="codex",
        stage="code_tester",
        prompt="hello",
        schema_inline="{}",
        schema_file=tmp_path / "schema.json",
        session_id="placeholder-session",
        resume=False,
    )
    result = CLIResult(
        command=command.command,
        returncode=0,
        stdout='{"type":"thread.started","thread_id":"thr-real"}\n',
        stderr="",
        metadata={"agent_command": command, "cwd": str(tmp_path)},
    )

    run_id = pipeline._record_run(iteration_id, "code_tester", result)
    worker_ref = pipeline.run_worker_ref(iteration_id, run_id)

    assert worker_ref["continueRef"]["threadId"] == "thr-real"
