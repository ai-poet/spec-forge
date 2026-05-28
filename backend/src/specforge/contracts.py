from __future__ import annotations

import json
from typing import Optional

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


class TesterArtifact(BaseModel):
    verify_report: str
    passed: bool
    failure_notes: Optional[str] = None
    adversarial_tests: list[ArtifactFile] = Field(default_factory=list)


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
