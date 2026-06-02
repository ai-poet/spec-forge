from __future__ import annotations

from typing import Annotated, Any, Optional

from typing_extensions import TypedDict


def _last_str(left: str | None, right: str | None) -> str | None:
    if right == "":
        return None
    return right if right is not None else left


def _last_value(left: Any | None, right: Any | None) -> Any | None:
    return right


def _merge_counts(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


class PipelineState(TypedDict, total=False):
    iteration_id: str
    project_id: Optional[str]
    project_name: str
    goal: str
    epic_title: Optional[str]
    epic_description: Optional[str]
    epic_acceptance_criteria: Optional[str]
    mode: str
    status: Annotated[str, _last_str]
    route: Annotated[str | None, _last_str]
    current_node: Annotated[Optional[str], _last_value]
    verify_approval: Optional[str]
    blocked_reason: Optional[str]
    failure_notes: Optional[str]
    retry_target: Optional[str]
    clarification_request: Optional[str]
    retry_counts: Annotated[dict[str, int], _merge_counts]
    max_coder_tester_retries: int
    max_tester_self_retries: int
    max_clarifications: int
    max_verify_rejects: int
    max_discovery_rounds: int
    requirements_brief: Annotated[str, _last_str]
    discovery_qa: list[dict[str, Any]]
    pending_discovery_question: Optional[str]
    pending_discovery_options: list[str]
    pending_discovery_assumptions: list[str]
    planning_cli_session_id: Optional[str]
    planning_cli_session_started: bool
    prd_planner_run_id: Optional[str]
    test_planner_run_id: Optional[str]
    coder_run_id: Optional[str]
    code_tester_run_id: Optional[str]
    verification_run_id: Optional[str]
    pending_code_tester_json: Optional[str]
