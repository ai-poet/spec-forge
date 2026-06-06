from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

CliProvider = Literal["claude", "codex"]
CliStage = Literal[
    "prd_planner",
    "test_planner",
    "planner_discovery",
    "planner_clarification",
    "coder",
    "code_tester",
    "ui_tester",
]

DEFAULT_CLI_BINDINGS: dict[CliStage, CliProvider] = {
    "prd_planner": "claude",
    "test_planner": "claude",
    "planner_discovery": "claude",
    "planner_clarification": "claude",
    "coder": "claude",
    "code_tester": "claude",
    "ui_tester": "claude",
}


def resolve_cli_provider(bindings: Optional[dict[str, str]], stage: CliStage) -> CliProvider:
    if bindings:
        value = bindings.get(stage)
        if value in ("claude", "codex"):
            return value  # type: ignore[return-value]
    return DEFAULT_CLI_BINDINGS[stage]


def parse_cli_bindings(raw: Optional[str]) -> Optional[dict[str, str]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): str(value) for key, value in payload.items() if value in ("claude", "codex")}


def serialize_cli_bindings(bindings: Optional[dict[str, str]]) -> Optional[str]:
    if not bindings:
        return None
    cleaned = {key: bindings[key] for key in DEFAULT_CLI_BINDINGS if bindings.get(key) in ("claude", "codex")}
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _claude_command(
    prompt: str,
    schema: str | Path,
    *,
    session_id: Optional[str] = None,
    resume: bool = False,
) -> list[str]:
    schema_arg = str(schema)
    cmd: list[str] = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--permission-mode",
        "bypassPermissions",
        "--verbose",
        "--include-partial-messages",
        "--include-hook-events",
    ]
    if session_id:
        if resume:
            cmd.extend(["--resume", session_id])
        else:
            cmd.extend(["--session-id", session_id])
    cmd.extend(["--json-schema", schema_arg, prompt])
    return cmd


def _codex_command(
    prompt: str,
    schema_file: Path,
    *,
    session_id: Optional[str] = None,
    resume: bool = False,
) -> list[str]:
    cmd = [
        "codex-sdk",
        "thread.run",
        "--output-schema",
        str(schema_file),
    ]
    return [
        *cmd,
        *(["--resume", session_id] if session_id and resume else []),
        prompt,
    ]


def build_cli_command(
    *,
    provider: CliProvider,
    prompt: str,
    schema_inline: str,
    schema_file: Path,
    session_id: Optional[str] = None,
    resume: bool = False,
) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file, session_id=session_id, resume=resume)
    return _claude_command(prompt, schema_inline, session_id=session_id, resume=resume)
