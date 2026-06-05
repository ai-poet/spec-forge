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
