from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from specforge.agents.codex_sdk_runner import CodexSdkRunner
from specforge.agents.providers import build_agent_command
from specforge.core.contracts import CodeTesterArtifact, parse_json_artifact


class FakeMode:
    auto_review = "auto_review"


class FakeSandbox:
    full_access = "full_access"


class FakeNotification:
    def __init__(self, payload):
        self.payload = payload


class FakeTurn:
    id = "turn-1"

    def __init__(self, events):
        self.events = events
        self.interrupted = False

    def stream(self):
        yield from self.events

    def interrupt(self):
        self.interrupted = True


class FakeThread:
    def __init__(self, thread_id: str, codex):
        self.id = thread_id
        self.codex = codex

    def turn(self, prompt, **kwargs):
        self.codex.turn_calls.append({"prompt": prompt, **kwargs})
        return FakeTurn(
            [
                FakeNotification({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(self.codex.artifact)}}),
                FakeNotification({"type": "turn.completed", "turn": {"id": "turn-1", "status": "completed", "duration_ms": 10}}),
            ]
        )


class FakeCodex:
    instances = []

    def __init__(self):
        self.started = []
        self.resumed = []
        self.turn_calls = []
        self.artifact = {
            "verify_report": "# Verify Report\n\n## Summary\n- Pass: 1\n- Fail: 0\n",
            "passed": True,
            "ux_notes": [],
            "delivery_recommendations": [],
            "adversarial_tests": [],
        }
        FakeCodex.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def thread_start(self, **kwargs):
        self.started.append(kwargs)
        return FakeThread("thr-start", self)

    def thread_resume(self, thread_id, **kwargs):
        self.resumed.append({"thread_id": thread_id, **kwargs})
        return FakeThread(thread_id, self)


def install_fake_openai_codex(monkeypatch):
    FakeCodex.instances.clear()
    module = types.SimpleNamespace(Codex=FakeCodex, ApprovalMode=FakeMode, Sandbox=FakeSandbox)
    monkeypatch.setitem(sys.modules, "openai_codex", module)


def test_codex_sdk_runner_passes_schema_and_wraps_structured_output(tmp_path, monkeypatch):
    install_fake_openai_codex(monkeypatch)
    command = build_agent_command(
        provider="codex",
        stage="code_tester",
        prompt="verify",
        schema_inline=json.dumps(CodeTesterArtifact.model_json_schema()),
        schema_file=tmp_path / "schema.json",
    )
    chunks: list[str] = []

    result = CodexSdkRunner().run_agent(
        command,
        cwd=tmp_path,
        on_output=lambda stream, chunk: chunks.append(chunk),
        iteration_id="iter-1",
    )

    assert result.returncode == 0
    assert result.metadata["codex_thread_id"] == "thr-start"
    assert FakeCodex.instances[0].started[0]["cwd"] == str(tmp_path)
    turn_call = FakeCodex.instances[0].turn_calls[0]
    assert turn_call["cwd"] == str(tmp_path)
    assert turn_call["approval_mode"] == FakeMode.auto_review
    assert turn_call["sandbox"] == FakeSandbox.full_access
    assert turn_call["output_schema"]["title"] == "CodeTesterArtifact"
    artifact = parse_json_artifact(result.stdout, CodeTesterArtifact)
    assert artifact.passed is True
    assert any('"structured_output"' in chunk for chunk in chunks)


def test_codex_sdk_runner_resumes_thread(tmp_path, monkeypatch):
    install_fake_openai_codex(monkeypatch)
    command = build_agent_command(
        provider="codex",
        stage="code_tester",
        prompt="continue",
        schema_inline=json.dumps(CodeTesterArtifact.model_json_schema()),
        schema_file=Path("/tmp/schema.json"),
        session_id="thr-existing",
        resume=True,
    )

    result = CodexSdkRunner().run_agent(command, cwd=tmp_path)

    assert result.returncode == 0
    assert result.metadata["codex_thread_id"] == "thr-existing"
    assert FakeCodex.instances[0].resumed[0]["thread_id"] == "thr-existing"
