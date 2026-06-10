from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal, Optional

from .cli_commands import CliProvider, CliStage, build_cli_command


SessionMode = Literal["new", "continue"]


@dataclass(frozen=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str
    output_schema: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_hash(self) -> str:
        payload = json.dumps(
            {
                "version": "0.1",
                "system_prompt": self.system_prompt,
                "user_prompt": self.user_prompt,
                "output_schema": self.output_schema,
                "metadata": self.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def payload(self, *, redact: bool = False) -> dict[str, Any]:
        return {
            "version": "0.1",
            "system_prompt": self.system_prompt,
            "user_prompt": "[redacted]" if redact else self.user_prompt,
            "output_schema": self.output_schema,
            "metadata": self.metadata,
            "prompt_hash": self.prompt_hash,
        }


@dataclass(frozen=True)
class WorkerRef:
    provider: CliProvider
    mode: SessionMode
    supports_open_session: bool
    supports_continue_session: bool
    continue_ref: dict[str, Any] | None = None
    open_command: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "version": "0.1",
            "provider": self.provider,
            "mode": self.mode,
            "supportsOpenSession": self.supports_open_session,
            "supportsContinueSession": self.supports_continue_session,
            "continueRef": self.continue_ref,
            "openCommand": self.open_command,
        }


@dataclass(frozen=True)
class AgentCommand:
    command: list[str]
    provider: CliProvider
    stage: CliStage
    prompt_bundle: PromptBundle
    stdin_text: str | None = None
    session_id: str | None = None
    session_mode: SessionMode = "new"
    continue_requested: bool = False
    continue_fallback_reason: str | None = None

    def public_command(self) -> str:
        if not self.command:
            return ""
        if self.stdin_text is not None:
            return f"{' '.join(self.command)} < [prompt omitted]"
        redacted = list(self.command)
        if redacted:
            redacted[-1] = "[prompt omitted]"
        return " ".join(redacted)

    def __iter__(self):
        return iter(self.command)

    def __len__(self) -> int:
        return len(self.command)

    def __getitem__(self, index):
        return self.command[index]


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: CliProvider
    display_name: str
    executable: str
    capabilities: dict[str, bool]
    install_hint: str


@dataclass(frozen=True)
class ProviderDoctor:
    provider_id: CliProvider
    available: bool
    status: Literal["ok", "error"]
    message: str
    detail: str | None = None
    version: str | None = None
    capabilities: dict[str, bool] = field(default_factory=dict)
    install_hint: str | None = None


class DirectCliProvider:
    def __init__(self, provider_id: CliProvider, *, display_name: str, executable: str, install_hint: str) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.executable = executable
        self.install_hint = install_hint

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self.provider_id,
            display_name=self.display_name,
            executable=self.executable,
            capabilities={
                "supports_open_session": True,
                "supports_continue_session": True,
                "supports_raw_stream": True,
                "supports_prompt_bundle": True,
            },
            install_hint=self.install_hint,
        )

    def doctor(self) -> ProviderDoctor:
        found = shutil.which(self.executable)
        if not found:
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message=f"`{self.executable}` not found on PATH",
                capabilities=self.describe().capabilities,
                install_hint=self.install_hint,
            )
        try:
            result = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message=f"`{self.executable} --version` failed",
                detail=str(exc),
                capabilities=self.describe().capabilities,
                install_hint=self.install_hint,
            )
        detail = _compact_output(result.stdout or result.stderr) or found
        if result.returncode != 0:
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message=f"`{self.executable} --version` exited {result.returncode}",
                detail=detail,
                capabilities=self.describe().capabilities,
                install_hint=self.install_hint,
            )
        return ProviderDoctor(
            provider_id=self.provider_id,
            available=True,
            status="ok",
            message="Available",
            detail=detail,
            version=detail,
            capabilities=self.describe().capabilities,
        )

    def open_session(self, worker_ref: WorkerRef) -> bool:
        return bool(self.build_continue_command(worker_ref))

    def build_continue_command(self, worker_ref: WorkerRef) -> str | None:
        ref = worker_ref.continue_ref or {}
        session_id = ref.get("sessionId") or ref.get("threadId")
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        if self.provider_id == "codex":
            return f"codex-sdk thread.run --resume {session_id}"
        return f"claude --resume {session_id}"


class CodexSdkProvider:
    provider_id: CliProvider = "codex"
    display_name = "Codex SDK"
    executable = "openai-codex"
    install_hint = "Install the OpenAI Codex Python SDK with `pip install openai-codex` and authenticate Codex."

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self.provider_id,
            display_name=self.display_name,
            executable=self.executable,
            capabilities={
                "supports_open_session": True,
                "supports_continue_session": True,
                "supports_raw_stream": True,
                "supports_prompt_bundle": True,
                "uses_python_sdk": True,
            },
            install_hint=self.install_hint,
        )

    def doctor(self) -> ProviderDoctor:
        # 1. Check SDK installation
        try:
            import openai_codex
            from openai_codex import Codex
        except ImportError as exc:
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message="openai-codex SDK not installed",
                detail=str(exc),
                capabilities=self.describe().capabilities,
                install_hint="Install the OpenAI Codex Python SDK: `pip install openai-codex` (requires Python 3.10+).",
            )
        except Exception as exc:
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message="openai-codex SDK import failed",
                detail=str(exc),
                capabilities=self.describe().capabilities,
                install_hint="Re-install the SDK: `pip install --force-reinstall openai-codex`.",
            )

        version = str(getattr(openai_codex, "__version__", "") or "unknown")

        # 2. Check runtime connectivity (auth + API reachability)
        try:
            with Codex() as codex:
                account = codex.account()
            detail = _compact_output(str(getattr(account, "account", None) or account)) or f"SDK {version}"
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=True,
                status="ok",
                message="Connected",
                detail=detail,
                version=version,
                capabilities=self.describe().capabilities,
            )
        except Exception as exc:
            exc_str = str(exc)
            # Classify common failure modes for better UX
            if "auth" in exc_str.lower() or "token" in exc_str.lower() or "key" in exc_str.lower() or "credential" in exc_str.lower():
                message = "Codex SDK installed, but authentication failed"
                install_hint = "Authenticate Codex: run `codex` in your terminal and follow the login flow, or set OPENAI_API_KEY."
            elif "connect" in exc_str.lower() or "network" in exc_str.lower() or "timeout" in exc_str.lower() or " unreachable" in exc_str.lower():
                message = "Codex SDK installed, but network/API unreachable"
                install_hint = "Check your network connection and OpenAI API status."
            else:
                message = "Codex SDK installed, but runtime check failed"
                install_hint = "Authenticate Codex via existing Codex login, ChatGPT device code, or API key."
            return ProviderDoctor(
                provider_id=self.provider_id,
                available=False,
                status="error",
                message=message,
                detail=exc_str,
                version=version,
                capabilities=self.describe().capabilities,
                install_hint=install_hint,
            )

    def open_session(self, worker_ref: WorkerRef) -> bool:
        return bool(self.build_continue_command(worker_ref))

    def build_continue_command(self, worker_ref: WorkerRef) -> str | None:
        ref = worker_ref.continue_ref or {}
        thread_id = ref.get("threadId")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return None
        return f"codex-sdk thread.run --resume {thread_id}"


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[CliProvider, DirectCliProvider | CodexSdkProvider] = {
            "claude": DirectCliProvider(
                "claude",
                display_name="Claude Code",
                executable="claude",
                install_hint="Install Claude Code CLI and ensure `claude` is available on PATH.",
            ),
            "codex": CodexSdkProvider(),
        }

    def provider(self, provider_id: CliProvider) -> DirectCliProvider | CodexSdkProvider:
        return self._providers[provider_id]

    def describe_all(self) -> list[ProviderInfo]:
        return [provider.describe() for provider in self._providers.values()]

    def doctor_all(self) -> list[ProviderDoctor]:
        return [provider.doctor() for provider in self._providers.values()]


PROVIDERS = ProviderRegistry()


def build_agent_command(
    *,
    provider: CliProvider,
    stage: CliStage,
    prompt: str,
    schema_inline: str,
    schema_file: Path,
    session_id: Optional[str] = None,
    resume: bool = False,
    continue_requested: bool = False,
    continue_fallback_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentCommand:
    command = build_cli_command(
        provider=provider,
        prompt=prompt,
        schema_inline=schema_inline,
        schema_file=schema_file,
        session_id=session_id,
        resume=resume,
    )
    prompt_bundle = PromptBundle(
        system_prompt=_system_prompt(stage=stage, provider=provider),
        user_prompt=prompt,
        output_schema=schema_inline,
        metadata={
            "stage": stage,
            "provider": provider,
            "schema_file": str(schema_file),
            "session_id": session_id,
            "session_mode": "continue" if resume and session_id else "new",
            **(metadata or {}),
        },
    )
    return AgentCommand(
        command=command,
        provider=provider,
        stage=stage,
        prompt_bundle=prompt_bundle,
        stdin_text=prompt if provider == "claude" else None,
        session_id=session_id,
        session_mode="continue" if resume and session_id else "new",
        continue_requested=continue_requested,
        continue_fallback_reason=continue_fallback_reason,
    )


def worker_ref_from_result(
    *,
    command: AgentCommand,
    stdout: str,
    stderr: str,
    cwd: Path | None,
) -> WorkerRef:
    extracted = extract_session_ref(command.provider, stdout=stdout, stderr=stderr)
    if command.provider == "codex":
        session_id = extracted.get("threadId") or command.session_id
    else:
        session_id = command.session_id or extracted.get("sessionId")
    continue_ref: dict[str, Any] | None = None
    if session_id:
        continue_ref = {
            "sessionId" if command.provider == "claude" else "threadId": session_id,
            "cwd": str(cwd) if cwd else None,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
        }
        if extracted:
            continue_ref["raw"] = extracted
    return WorkerRef(
        provider=command.provider,
        mode=command.session_mode,
        supports_open_session=bool(session_id),
        supports_continue_session=bool(session_id),
        continue_ref=continue_ref,
        open_command=None,
    )


def extract_session_ref(provider: CliProvider, *, stdout: str, stderr: str = "") -> dict[str, Any]:
    for line in _json_lines(stdout, stderr):
        if provider == "claude":
            session_id = _first_str(line, "session_id", "sessionId")
            if session_id:
                return {"sessionId": session_id}
            if line.get("type") == "system" and isinstance(line.get("message"), dict):
                nested = _first_str(line["message"], "session_id", "sessionId")
                if nested:
                    return {"sessionId": nested}
        if provider == "codex":
            thread_id = _first_str(line, "thread_id", "threadId", "id")
            if str(line.get("type") or line.get("event") or "").startswith("thread.") and thread_id:
                return {"threadId": thread_id}
            msg = line.get("msg")
            if isinstance(msg, dict):
                nested = _first_str(msg, "thread_id", "threadId", "id")
                if nested and str(line.get("type") or line.get("event") or msg.get("type") or "").startswith("thread."):
                    return {"threadId": nested}
    return {}


def validate_worker_ref(payload: dict[str, Any]) -> bool:
    if payload.get("version") is None:
        return False
    if payload.get("provider") not in {"claude", "codex"}:
        return False
    if payload.get("mode") not in {"new", "continue"}:
        return False
    return isinstance(payload.get("supportsOpenSession"), bool) and isinstance(payload.get("supportsContinueSession"), bool)


def _system_prompt(*, stage: CliStage, provider: CliProvider) -> str:
    return (
        "You are running inside SpecForge, a local spec-first agent pipeline. "
        f"Current stage: {stage}. Provider: {provider}. "
        "Respect the stage instructions, write-zone constraints, and final <specforge_artifact> JSON contract."
    )


def _json_lines(*texts: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for text in texts:
        for raw in (text or "").splitlines():
            raw = raw.strip()
            if not raw or not raw.startswith("{"):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return items


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _compact_output(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[0][:240] if lines else None
