from __future__ import annotations

from typing import Literal

from ..core.models import IterationStatus
from .state import PipelineState


class PipelineRoutesMixin:

    def _route_after_discovery(self, state: PipelineState) -> Literal["blocked", "ask", "ready"]:
        if state.get("status") in {
            IterationStatus.blocked.value,
            IterationStatus.blocked_user.value,
            IterationStatus.stopped.value,
        }:
            return "blocked"
        if state.get("route") == "ask":
            return "ask"
        return "ready"


    def _route_after_prd_planner(self, state: PipelineState) -> Literal["blocked", "test_planner"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        return "test_planner"


    def _route_after_test_planner(self, state: PipelineState) -> Literal["blocked", "coder", "test_planner_retry"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "test_planner_retry":
            return "test_planner_retry"
        return "coder"


    def _route_after_coder(self, state: PipelineState) -> Literal["blocked", "clarification", "integrity"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "clarification":
            return "clarification"
        return "integrity"


    def _route_after_clarification(self, state: PipelineState) -> Literal["blocked", "coder"]:
        return "blocked" if state.get("status") in {IterationStatus.blocked.value, IterationStatus.blocked_user.value, IterationStatus.stopped.value} else "coder"


    def _route_after_integrity(self, state: PipelineState) -> Literal["blocked", "code_tester"]:
        return "blocked" if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value} else "code_tester"


    def _route_after_code_tester(
        self, state: PipelineState
    ) -> Literal["blocked", "ui", "retry", "self_retry", "test_planner_retry"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        route = state.get("route")
        if route in {"retry", "self_retry", "test_planner_retry"}:
            return route  # type: ignore[return-value]
        if not state.get("pending_code_tester_json"):
            return "blocked"
        return "ui"


    def _route_after_ui_tester(self, state: PipelineState) -> Literal["blocked", "retry", "self_retry", "test_planner_retry", "verify"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "test_planner_retry":
            return "test_planner_retry"
        if state.get("route") == "self_retry":
            return "self_retry"
        if state.get("route") == "retry":
            return "retry"
        return "verify"


    def _route_after_planner_verify(self, state: PipelineState) -> Literal["blocked", "code_tester", "approval"]:
        if state.get("status") in {IterationStatus.blocked.value, IterationStatus.stopped.value}:
            return "blocked"
        if state.get("route") == "verify_rejected":
            return "code_tester"
        return "approval"
