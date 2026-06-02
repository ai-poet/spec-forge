from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .state import PipelineState


class PipelineGraphMixin:

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(PipelineState)
        builder.add_node("planner_discovery", self._planner_discovery_node)
        builder.add_node("requirements_input", self._requirements_input_node)
        builder.add_node("prd_planner", self._prd_planner_node)
        builder.add_node("test_planner", self._test_planner_node)
        builder.add_node("coder", self._coder_node)
        builder.add_node("planner_clarification", self._planner_clarification_node)
        builder.add_node("integrity_check", self._integrity_check_node)
        builder.add_node("code_tester", self._code_tester_node)
        builder.add_node("ui_tester", self._ui_tester_node)
        builder.add_node("planner_verify", self._planner_verify_node)
        builder.add_node("verify_approval", self._verify_approval_node)
        builder.add_node("done", self._done_node)
        builder.add_edge(START, "planner_discovery")
        builder.add_conditional_edges(
            "planner_discovery",
            self._route_after_discovery,
            {"blocked": END, "ask": "requirements_input", "ready": "prd_planner"},
        )
        builder.add_edge("requirements_input", "planner_discovery")
        builder.add_conditional_edges("prd_planner", self._route_after_prd_planner, {"blocked": END, "test_planner": "test_planner"})
        builder.add_conditional_edges("test_planner", self._route_after_test_planner, {"blocked": END, "coder": "coder", "test_planner_retry": "test_planner"})
        builder.add_conditional_edges(
            "coder",
            self._route_after_coder,
            {"blocked": END, "clarification": "planner_clarification", "code_tester": "code_tester"},
        )
        builder.add_conditional_edges(
            "planner_clarification",
            self._route_after_clarification,
            {"blocked": END, "coder": "coder"},
        )
        builder.add_conditional_edges("integrity_check", self._route_after_integrity, {"blocked": END, "ui_tester": "ui_tester"})
        builder.add_conditional_edges(
            "code_tester",
            self._route_after_code_tester,
            {
                "blocked": END,
                "integrity": "integrity_check",
                "retry": "coder",
                "self_retry": "code_tester",
                "test_planner_retry": "test_planner",
            },
        )
        builder.add_conditional_edges(
            "ui_tester",
            self._route_after_ui_tester,
            {"blocked": END, "retry": "coder", "self_retry": "code_tester", "test_planner_retry": "test_planner", "verify": "planner_verify"},
        )
        builder.add_conditional_edges("planner_verify", self._route_after_planner_verify, {"blocked": END, "code_tester": "code_tester", "approval": "verify_approval"})
        builder.add_edge("verify_approval", "done")
        builder.add_edge("done", END)
        return builder
