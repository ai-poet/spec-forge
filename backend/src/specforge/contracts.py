from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError


class ArtifactFile(BaseModel):
    path: str = Field(min_length=1)
    content: str


class PlannerArtifact(BaseModel):
    system_design: str
    modification_plan: str
    testing_plan: str
    tests: list[ArtifactFile] = Field(default_factory=list)


class CoderArtifact(BaseModel):
    changed_paths: list[str] = Field(default_factory=list)
    summary: str = ""
    clarification_request: Optional[str] = None


class UITestTarget(BaseModel):
    url: Optional[str] = None
    bundle_id: Optional[str] = None
    app_name: Optional[str] = None
    chrome_bundle_id: str = "com.google.Chrome"


class UITestStep(BaseModel):
    action: Literal["assert_text", "click_text", "type_text", "press_key", "hotkey", "scroll", "screenshot"]
    text: Optional[str] = None
    value: Optional[str] = None
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


class UIArtifactLink(BaseModel):
    label: str
    path: str


class UITestResult(BaseModel):
    id: str
    title: str = ""
    kind: Literal["web", "native"]
    status: Literal["passed", "failed", "skipped", "warning"]
    target: str = ""
    error: Optional[str] = None
    observations: list[str] = Field(default_factory=list)
    artifacts: list[UIArtifactLink] = Field(default_factory=list)


class UIDriverRunResult(BaseModel):
    available: bool
    warning: Optional[str] = None
    results: list[UITestResult] = Field(default_factory=list)


class TesterArtifact(BaseModel):
    verify_report: str
    passed: bool
    failure_notes: Optional[str] = None
    ux_notes: list[str] = Field(default_factory=list)
    delivery_recommendations: list[str] = Field(default_factory=list)
    ui_results: list[UITestResult] = Field(default_factory=list)
    ui_warnings: list[str] = Field(default_factory=list)
    adversarial_tests: list[ArtifactFile] = Field(default_factory=list)

    @property
    def ui_failed(self) -> bool:
        return any(result.status == "failed" for result in self.ui_results)


def parse_json_artifact(raw: str, model: type[BaseModel]) -> BaseModel:
    text = raw.strip()
    if not text:
        raise ValueError("empty artifact output")
    payload = _decode_payload(text)
    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], str):
        payload = _decode_payload(payload["result"].strip())
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _decode_payload(text: str):
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
