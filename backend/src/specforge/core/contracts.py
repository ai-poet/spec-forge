from __future__ import annotations

import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator


class ArtifactFile(BaseModel):
    path: str = Field(min_length=1)
    content: str


class ContextManifestEntry(BaseModel):
    file: str = Field(min_length=1)
    reason: str = ""
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    public_api: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    sha256: Optional[str] = None
    last_scanned_at: Optional[str] = None
    freshness: Optional[str] = None


class PrdPlannerArtifact(BaseModel):
    prd: str
    context_for_coder: list[ContextManifestEntry] = Field(default_factory=list)
    context_for_tester: list[ContextManifestEntry] = Field(default_factory=list)


class TestPlannerArtifact(BaseModel):
    testing_plan: str


class PlannerDiscoveryArtifact(BaseModel):
    status: Literal["ask", "ready"]
    complexity: Literal["trivial", "simple", "moderate", "complex"] = "moderate"
    question: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    requirements_brief: str = ""
    rationale: str = ""

    @model_validator(mode="after")
    def validate_ask_options(self) -> "PlannerDiscoveryArtifact":
        if self.status != "ask":
            return self
        from ..policy.discovery_options import DISCOVERY_CUSTOM_OPTION_LABEL, normalize_discovery_options

        if not (self.question or "").strip():
            raise ValueError("ask status requires question")
        object.__setattr__(self, "options", normalize_discovery_options(self.options))
        if self.options[-1] != DISCOVERY_CUSTOM_OPTION_LABEL:
            raise ValueError(f"last option must be '{DISCOVERY_CUSTOM_OPTION_LABEL}'")
        return self


class PlannerClarificationArtifact(BaseModel):
    answer: str
    summary: str = ""


class CoderArtifact(BaseModel):
    changed_paths: list[str] = Field(default_factory=list)
    summary: str = ""
    clarification_request: Optional[str] = None


class UITestTarget(BaseModel):
    url: Optional[str] = None
    bundle_id: Optional[str] = None
    app_name: Optional[str] = None
    chrome_bundle_id: str = "com.google.Chrome"


UITestAction = Literal[
    "assert_text",
    "assert_text_match",
    "assert_missing",
    "assert_visible",
    "click_text",
    "type_text",
    "press_key",
    "hotkey",
    "scroll",
    "screenshot",
    "wait",
    "resize_window",
]


class UITestStep(BaseModel):
    action: UITestAction
    text: Optional[str] = None
    value: Optional[str] = None
    selector: Optional[str] = None
    key: Optional[str] = None
    keys: list[str] = Field(default_factory=list)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=1, ge=1, le=20)


class UITestSpec(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    title: str = ""
    kind: Literal["web", "native"]
    target: UITestTarget
    steps: list[UITestStep] = Field(default_factory=list)


UI_TEST_ACTIONS = (
    "assert_text",
    "assert_text_match",
    "assert_missing",
    "assert_visible",
    "click_text",
    "type_text",
    "press_key",
    "hotkey",
    "scroll",
    "screenshot",
    "wait",
    "resize_window",
)


ARTIFACT_OPEN_TAG = "<specforge_artifact>"
ARTIFACT_CLOSE_TAG = "</specforge_artifact>"


def validate_ui_spec_content(path: str, content: str) -> UITestSpec:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid UI spec {path}: {exc}") from exc
    try:
        return UITestSpec.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid UI spec {path}: {exc}") from exc


def ui_spec_error_type(message: str) -> str:
    return "ui_spec.invalid" if message.startswith("invalid UI spec ") else "artifact.invalid"


class UIArtifactLink(BaseModel):
    label: str
    path: str


class UITestResult(BaseModel):
    id: str
    title: str = ""
    kind: Literal["web", "native"]
    status: Literal["passed", "failed", "skipped", "warning"]
    target: str = ""
    driver: Optional[Literal["cua", "playwright"]] = None
    error: Optional[str] = None
    observations: list[str] = Field(default_factory=list)
    artifacts: list[UIArtifactLink] = Field(default_factory=list)


class UIDriverRunResult(BaseModel):
    available: bool
    warning: Optional[str] = None
    fallback: Optional[Literal["playwright"]] = None
    cua_busy: bool = False
    cua_session_holder: Optional[str] = None
    results: list[UITestResult] = Field(default_factory=list)


class Defect(BaseModel):
    severity: Literal["P0", "P1", "P2"] = "P1"
    path: Optional[str] = None
    owner: Optional[Literal["coder", "code_tester", "test_planner", "prd_planner"]] = None
    message: str = Field(min_length=1)


class CodeTesterArtifact(BaseModel):
    verify_report: str
    passed: bool
    failure_notes: Optional[str] = None
    defects: list[Defect] = Field(default_factory=list)
    ux_notes: list[str] = Field(default_factory=list)
    delivery_recommendations: list[str] = Field(default_factory=list)
    adversarial_tests: list[ArtifactFile] = Field(default_factory=list)
    test_files: list[ArtifactFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_file_zones(self) -> "CodeTesterArtifact":
        _move_adversarial_test_files(self)
        return self


def verification_from_code(artifact: CodeTesterArtifact) -> "VerificationArtifact":
    return VerificationArtifact.model_validate(artifact.model_dump())


class VerificationArtifact(BaseModel):
    verify_report: str
    passed: bool
    failure_notes: Optional[str] = None
    defects: list[Defect] = Field(default_factory=list)
    ux_notes: list[str] = Field(default_factory=list)
    delivery_recommendations: list[str] = Field(default_factory=list)
    ui_results: list[UITestResult] = Field(default_factory=list)
    ui_warnings: list[str] = Field(default_factory=list)
    adversarial_tests: list[ArtifactFile] = Field(default_factory=list)
    test_files: list[ArtifactFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_file_zones(self) -> "VerificationArtifact":
        _move_adversarial_test_files(self)
        return self

    @property
    def ui_failed(self) -> bool:
        return any(result.status == "failed" for result in self.ui_results)


def _move_adversarial_test_files(artifact: CodeTesterArtifact | VerificationArtifact) -> None:
    misplaced = [file for file in artifact.test_files if _is_adversarial_test_path(file.path)]
    if not misplaced:
        return
    artifact.test_files = [file for file in artifact.test_files if not _is_adversarial_test_path(file.path)]
    adversarial_by_path = {file.path: file for file in artifact.adversarial_tests}
    for file in misplaced:
        adversarial_by_path[file.path] = file
    artifact.adversarial_tests = list(adversarial_by_path.values())


def _is_adversarial_test_path(path: str) -> bool:
    return path.replace("\\", "/").lstrip("./").startswith("tests/adversarial/")


def merge_cli_artifact_output(stdout: str, stderr: str) -> str:
    out = stdout.strip()
    err = stderr.strip()
    if out and err:
        return f"{out}\n{err}"
    return out or err


def parse_json_artifact(raw: str, model: type[BaseModel]) -> BaseModel:
    text = raw.strip()
    if not text:
        raise ValueError("empty artifact output")
    payload = _decode_payload(_artifact_candidate(text))
    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], str):
        payload = _decode_payload(payload["result"].strip())
    if isinstance(payload, dict) and "structured_output" in payload:
        payload = payload["structured_output"]
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _artifact_candidate(text: str):
    tagged = _last_tagged_artifact(text)
    if tagged is not None:
        return tagged
    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = _artifact_from_event(payload)
        if candidate is not None:
            return candidate
    fenced = _last_json_code_block(text)
    if fenced is not None:
        return fenced
    balanced = _last_balanced_json_object(text)
    return balanced or text


def _last_tagged_artifact(text: str) -> str | None:
    start = text.rfind(ARTIFACT_OPEN_TAG)
    if start < 0:
        return None
    start += len(ARTIFACT_OPEN_TAG)
    end = text.find(ARTIFACT_CLOSE_TAG, start)
    if end < 0:
        return None
    candidate = text[start:end].strip()
    if not candidate:
        return None
    return _unescape_json_string_fragment(candidate)


def _unescape_json_string_fragment(text: str) -> str:
    if "\\\"" not in text and "\\n" not in text and "\\t" not in text:
        return text
    try:
        decoded = json.loads(f'"{text}"')
    except json.JSONDecodeError:
        return text
    return decoded.strip()


def _last_json_code_block(text: str) -> str | None:
    matches = list(re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL))
    for match in reversed(matches):
        candidate = match.group(1).strip()
        if candidate:
            return candidate
    return None


def _last_balanced_json_object(text: str) -> str | None:
    end = text.rfind("}")
    if end < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(end, -1, -1):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "}":
            depth += 1
            continue
        if char == "{":
            depth -= 1
            if depth == 0:
                return text[index : end + 1].strip()
    return None


def _artifact_from_event(payload):
    if not isinstance(payload, dict):
        return None
    if "structured_output" in payload:
        return payload["structured_output"]
    if isinstance(payload.get("result"), str):
        return payload["result"].strip()
    item = payload.get("item")
    if isinstance(item, dict):
        candidate = _artifact_from_event(item)
        if candidate is not None:
            return candidate
        if item.get("type") in {"agent_message", "agentMessage", "message"} and isinstance(item.get("text"), str):
            return item["text"].strip()
    params = payload.get("params")
    if isinstance(params, dict):
        candidate = _artifact_from_event(params)
        if candidate is not None:
            return candidate
    if payload.get("type") == "assistant":
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                text = "".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
                if text.strip():
                    return text.strip()
    return None


def _decode_payload(text: str):
    if isinstance(text, dict):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                if isinstance(payload.get("result"), str):
                    return _decode_payload(payload["result"].strip())
                if isinstance(payload.get("message"), str):
                    return _decode_payload(payload["message"].strip())
                if isinstance(payload.get("content"), str):
                    return _decode_payload(payload["content"].strip())
                return payload
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise
        return json.loads(text[start : end + 1])
