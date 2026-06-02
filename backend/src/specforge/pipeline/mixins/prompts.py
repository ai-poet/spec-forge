from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel

from ...agents.cli_commands import CliStage, build_cli_command, parse_cli_bindings, resolve_cli_provider
from ...agents.prompt_loader import compose_stage_prompt
from ...core.contracts import (
    CodeTesterArtifact,
    CoderArtifact,
    PlannerClarificationArtifact,
    PlannerDiscoveryArtifact,
    PrdPlannerArtifact,
    TestPlannerArtifact,
)
from ...core.models import IterationStatus, NodeName
from ...policy.artifact_gate import read_convention_excerpt, read_framework_conventions, read_spec_index
from ...policy.context_manifest import (
    FOR_CODER,
    FOR_TESTER,
    RUNTIME_NOTES,
    format_manifest_for_prompt,
    format_runtime_notes_section,
)

from ..state import PipelineState


class PipelinePromptsMixin:

    def _workflow_state_section(self, state: PipelineState, *, node: str) -> str:
        current = state.get("current_node") or node
        status = state.get("status") or ""
        route = state.get("route") or ""
        parts = [f"node: {current}", f"status: {status}"]
        if route:
            parts.append(f"route: {route}")
        body = "\n".join(parts)
        return f"<workflow-state>\n{body}\n</workflow-state>"


    def _context_manifest_prompt(self, iteration_id: str, manifest_rel: str, *, heading: str) -> str:
        path = self.docs_root(iteration_id) / manifest_rel
        if not path.exists():
            return ""
        from ...policy.context_manifest import read_jsonl

        return format_manifest_for_prompt(read_jsonl(path), heading=heading)


    def _runtime_notes_prompt(self, iteration_id: str) -> str:
        path = self.docs_root(iteration_id) / RUNTIME_NOTES
        return format_runtime_notes_section(path)


    def _project_convention_prompt(self, repo_root: Path) -> str:
        convention = read_convention_excerpt(repo_root)
        if not convention:
            return ""
        return f"Project docs/00_convention.md:\n{convention}\n"


    def _spec_index_prompt(self, repo_root: Path) -> str:
        index = read_spec_index(repo_root)
        if not index:
            return ""
        return f"Project docs/spec-index.md:\n{index}\n"


    def _planner_brief(self, state: PipelineState) -> str:
        iteration_id = state["iteration_id"]
        docs_root = self.docs_root(iteration_id)
        repo_root = self.project_repo_root(iteration_id)
        parts = [
            f"Iteration goal: {state['goal']}",
            f"Project docs root: {repo_root / 'docs'}",
            f"Iteration docs root: {docs_root}",
            "Read docs/00_convention.md and docs/01_project_goal.md before planning. "
            "If docs/00_convention.md is still the default stub, update it with this repo's source/test layout (real-cli) or record layout in prd.md. "
            "If docs/03_invariants/ or docs/04_decisions/ exist, read relevant entries; create them only when needed. "
            "If docs/spec-index.md exists, honor it when building context manifests.",
        ]
        if state.get("epic_title"):
            parts.append(f"Epic title: {state['epic_title']}")
        if state.get("epic_description"):
            parts.append(f"Epic description: {state['epic_description']}")
        if state.get("epic_acceptance_criteria"):
            parts.append(f"Epic acceptance criteria: {state['epic_acceptance_criteria']}")
        return "\n".join(parts)


    def _discovery_context_prompt(self, state: PipelineState) -> str:
        parts: list[str] = []
        brief = (state.get("requirements_brief") or "").strip()
        if brief:
            parts.append(f"Current requirements brief:\n{brief}")
        qa_text = self._format_discovery_qa_for_prompt(state.get("discovery_qa") or [])
        if qa_text:
            parts.append(f"Prior discovery Q&A:\n{qa_text}")
        if not parts:
            return "(no prior discovery context)"
        return "\n\n".join(parts)


    @staticmethod
    def _format_discovery_qa_for_prompt(discovery_qa: list[dict[str, Any]]) -> str:
        if not discovery_qa:
            return ""
        lines: list[str] = []
        for item in discovery_qa:
            round_num = item.get("round", "?")
            question = item.get("question", "")
            answer = item.get("answer", "")
            lines.append(f"Round {round_num} Q: {question}")
            lines.append(f"Round {round_num} A: {answer}")
        return "\n".join(lines)


    def _synthesize_requirements_brief(
        self,
        state: PipelineState,
        *,
        discovery_qa: list[dict[str, Any]],
        assumptions: list[str],
    ) -> str:
        goal = state["goal"]
        parts = [f"Goal: {goal}"]
        prior = (state.get("requirements_brief") or "").strip()
        if prior and prior not in parts[0]:
            parts.append(f"\nPrior brief notes:\n{prior}")
        qa_text = self._format_discovery_qa_for_prompt(discovery_qa)
        if qa_text:
            parts.append(f"\nDiscovery Q&A:\n{qa_text}")
        if assumptions:
            parts.append("\nAssumptions:\n" + "\n".join(f"- {item}" for item in assumptions))
        parts.append("\nProceed to system design, modification plan, testing plan, and protected tests in one planning pass.")
        return "\n".join(parts).strip()


    @staticmethod
    def _discovery_brief_markdown(brief: str, assumptions: list[str], complexity: str) -> str:
        assumption_lines = "\n".join(f"- {item}" for item in assumptions) if assumptions else "- (none)"
        body = brief.strip() or "(evolving)"
        return (
            "---\ndoc: requirements_brief\nstatus: draft\nowner: user\n---\n\n"
            f"# Requirements Brief\n\n**Complexity:** {complexity}\n\n## Summary\n\n{body}\n\n"
            f"## Assumptions\n\n{assumption_lines}\n"
        )


    def _discovery_snapshot_fields(self, iteration_id: str) -> dict[str, Any]:
        graph_state = self.graph.get_state(self._config(iteration_id))
        values = graph_state.values or {}
        discovery_qa = list(values.get("discovery_qa") or [])
        history = [
            {
                "round": int(item.get("round", index + 1)),
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
            }
            for index, item in enumerate(discovery_qa)
        ]
        pending: dict[str, Any] | None = None
        question = values.get("pending_discovery_question")
        if question:
            pending = {
                "round": len(discovery_qa) + 1,
                "question": str(question),
                "options": list(values.get("pending_discovery_options") or []),
                "assumptions": list(values.get("pending_discovery_assumptions") or []),
            }
        else:
            row = self.db.get_iteration_row(iteration_id)
            awaiting_input = (
                row is not None
                and row["status"] == IterationStatus.awaiting_requirements_input.value
            ) or "requirements_input" in set(graph_state.next or [])
            if awaiting_input:
                pending = self._pending_discovery_from_events(iteration_id, round_num=len(discovery_qa) + 1)
        return {"pending_discovery": pending, "discovery_history": history}


    def _pending_discovery_from_events(self, iteration_id: str, *, round_num: int) -> dict[str, Any] | None:
        for event in reversed(self.db.list_events(iteration_id)):
            if event["type"] != "discovery.question":
                continue
            try:
                payload = json.loads(event["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            question = str(payload.get("question") or "").strip()
            if not question:
                continue
            raw_options = payload.get("options") or []
            raw_assumptions = payload.get("assumptions") or []
            return {
                "round": int(payload.get("round") or round_num),
                "question": question,
                "options": [str(item) for item in raw_options] if isinstance(raw_options, list) else [],
                "assumptions": [str(item) for item in raw_assumptions] if isinstance(raw_assumptions, list) else [],
            }
        return None


    def _cli_provider(self, state: PipelineState, stage: CliStage) -> str:
        raw = self._project_field(state, "cli_bindings")
        bindings = parse_cli_bindings(raw)
        return resolve_cli_provider(bindings, stage)


    def _ensure_planning_session_id(self, state: PipelineState) -> str:
        existing = state.get("planning_cli_session_id")
        if existing:
            return existing
        session_id = str(uuid4())
        state["planning_cli_session_id"] = session_id
        return session_id


    def _planning_session_started(self, state: PipelineState) -> bool:
        return bool(state.get("planning_cli_session_started"))


    def _mark_planning_session_started(self, state: PipelineState) -> None:
        state["planning_cli_session_started"] = True


    def _planner_discovery_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            repo_root = self.project_repo_root(iteration_id)
            session_id = self._ensure_planning_session_id(state)
            resume = self._planning_session_started(state)
            prompt = compose_stage_prompt(
                "planner_discovery",
                repo_root=repo_root,
                variables={
                    "schema_hint": (
                        "{status:ask|ready, complexity:trivial|simple|moderate|complex, "
                        "question?:string, options:[string] (required when ask; last must be 其他（请说明）), "
                        "assumptions:[string], "
                        "requirements_brief:string, rationale:string}"
                    ),
                    "brief": self._planner_brief(state),
                    "discovery_context": self._discovery_context_prompt(state),
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root) + self._spec_index_prompt(repo_root),
                    "workflow_state": self._workflow_state_section(state, node=NodeName.planner_discovery.value),
                    "session_continuation": self._discovery_continuation_hint(state, resume=resume),
                },
            )
            provider = self._cli_provider(state, "planner_discovery")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PlannerDiscoveryArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "planner_discovery_artifact", PlannerDiscoveryArtifact),
                session_id=session_id,
                resume=resume,
            )
        return ["specforge", "planner_discovery", iteration_id]


    def _discovery_continuation_hint(self, state: PipelineState, *, resume: bool) -> str:
        if not resume:
            return "(first discovery turn — produce a question or mark ready based on the brief above)"
        discovery_qa = state.get("discovery_qa") or []
        if not discovery_qa:
            return "(continuing planning session)"
        latest = discovery_qa[-1]
        return (
            "Continuation of the same planning session. The user just answered:\n"
            f"  Q{latest.get('round', '?')}: {latest.get('question', '')}\n"
            f"  A{latest.get('round', '?')}: {latest.get('answer', '')}\n"
            "Decide whether to ask another high-value clarifying question (status=ask) "
            "or proceed (status=ready). Do not repeat earlier answers — refine the brief."
        )


    def _prd_planner_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        brief = self._planner_brief(state)
        requirements_brief = (state.get("requirements_brief") or "").strip() or "(see iteration goal and discovery docs)"
        discovery_qa = self._format_discovery_qa_for_prompt(state.get("discovery_qa") or []) or "(none)"
        if self._is_real_cli(state.get("mode")):
            repo_root = self.project_repo_root(iteration_id)
            session_id = self._ensure_planning_session_id(state)
            resume = self._planning_session_started(state)
            prompt = compose_stage_prompt(
                "prd_planner",
                repo_root=repo_root,
                variables={
                    "schema_hint": (
                        "{prd:string, "
                        "context_for_coder:[{file:string, reason:string}], "
                        "context_for_tester:[{file:string, reason:string}]}"
                    ),
                    "brief": brief,
                    "requirements_brief": requirements_brief,
                    "discovery_qa": discovery_qa,
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root) + self._spec_index_prompt(repo_root),
                    "workflow_state": self._workflow_state_section(state, node=NodeName.prd_planner.value),
                    "session_continuation": self._stage_continuation_hint(stage="prd_planner", resume=resume),
                },
            )
            provider = self._cli_provider(state, "prd_planner")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PrdPlannerArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "prd_planner_artifact", PrdPlannerArtifact),
                session_id=session_id,
                resume=resume,
            )
        return ["specforge", "prd_planner", iteration_id]


    def _test_planner_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        brief = self._planner_brief(state)
        requirements_brief = (state.get("requirements_brief") or "").strip() or "(see prd.md)"
        if self._is_real_cli(state.get("mode")):
            repo_root = self.project_repo_root(iteration_id)
            session_id = self._ensure_planning_session_id(state)
            resume = self._planning_session_started(state)
            prompt = compose_stage_prompt(
                "test_planner",
                repo_root=repo_root,
                variables={
                    "schema_hint": "{testing_plan:string}",
                    "brief": brief,
                    "requirements_brief": requirements_brief,
                    "failure_notes": state.get("failure_notes") or "(none)",
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root) + self._spec_index_prompt(repo_root),
                    "workflow_state": self._workflow_state_section(state, node=NodeName.test_planner.value),
                    "session_continuation": self._stage_continuation_hint(stage="test_planner", resume=resume),
                },
            )
            provider = self._cli_provider(state, "test_planner")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(TestPlannerArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "test_planner_artifact", TestPlannerArtifact),
                session_id=session_id,
                resume=resume,
            )
        return ["specforge", "test_planner", iteration_id]


    @staticmethod
    def _stage_continuation_hint(*, stage: str, resume: bool) -> str:
        if not resume:
            return "(starting planning session — produce only this stage's artifact)"
        if stage == "prd_planner":
            return (
                "Same planning session as discovery. Discovery context (brief and Q&A) is already in this session — "
                "do not re-summarize it. Produce ONLY the PRD artifact for this turn."
            )
        if stage == "test_planner":
            return (
                "Same planning session as discovery and PRD. The PRD is already in this session — "
                "do not regenerate it. Produce ONLY the testing_plan and protected tests for this turn. "
                "If this turn is a retry after a verification failure, focus on the failure notes."
            )
        return "(continuation of planning session)"


    def _planner_clarification_command(self, state: PipelineState, clarification_request: str) -> list[str]:
        if self._is_real_cli(state.get("mode")):
            iteration_id = state["iteration_id"]
            docs_root = self.docs_root(iteration_id)
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "planner_clarification",
                repo_root=repo_root,
                variables={
                    "docs_root": str(docs_root),
                    "schema_hint": "{answer:string, summary:string}",
                    "clarification_request": clarification_request,
                    "context_manifest": self._context_manifest_prompt(
                        iteration_id,
                        FOR_CODER,
                        heading="Coder context manifest (for_coder.jsonl):",
                    ),
                    "runtime_notes": self._runtime_notes_prompt(iteration_id),
                },
            )
            provider = self._cli_provider(state, "planner_clarification")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(PlannerClarificationArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "planner_clarification_artifact", PlannerClarificationArtifact),
            )
        return ["specforge", "planner_clarification", state["iteration_id"]]


    def _coder_command(self, state: PipelineState) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            notes = state.get("failure_notes") or ""
            docs_root = self.docs_root(iteration_id)
            repo_root = self.project_repo_root(iteration_id)
            prompt = compose_stage_prompt(
                "coder",
                repo_root=repo_root,
                variables={
                    "docs_root": str(docs_root),
                    "schema_hint": "{changed_paths:[string], summary:string, clarification_request?:string}",
                    "failure_notes": notes or "(none)",
                    "framework_conventions": read_framework_conventions(),
                    "convention_excerpt": self._project_convention_prompt(repo_root),
                    "context_manifest": self._context_manifest_prompt(
                        iteration_id,
                        FOR_CODER,
                        heading="Required context files (read only these paths):",
                    ),
                    "runtime_notes": self._runtime_notes_prompt(iteration_id),
                },
            )
            provider = self._cli_provider(state, "coder")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(CoderArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "coder_artifact", CoderArtifact),
            )
        return ["specforge", "coder", iteration_id]


    def _code_tester_command(self, state: PipelineState, *, review_only: bool = False, fallback_reason: str = "") -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = self._code_tester_prompt(state, review_only=review_only, fallback_reason=fallback_reason)
            provider = self._cli_provider(state, "code_tester")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(CodeTesterArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "code_tester_artifact", CodeTesterArtifact),
            )
        return ["specforge", "code_tester", iteration_id]


    def _code_tester_prompt(self, state: PipelineState, *, review_only: bool, fallback_reason: str = "") -> str:
        iteration_id = state["iteration_id"]
        row = self._require_iteration(iteration_id)
        docs_root = self.docs_root(iteration_id)
        repo_root = self.project_repo_root(iteration_id)
        test_command = row["test_command"] if "test_command" in row.keys() else None
        build_command = row["build_command"] if "build_command" in row.keys() else None
        if not build_command and state.get("project_id"):
            build_command = self._project_field(state, "default_build_command")

        retry_notes_section = ""
        if state.get("failure_notes"):
            retry_notes_section = (
                "Retry notes to address in the Tester artifact: "
                f"{state.get('failure_notes')}. "
                "If Planner verification rejected verify_report.md structure, regenerate verify_report with a Markdown title, "
                "a Summary section, and explicit Pass/Fail counts; this is a Tester docs artifact, not a Coder src/** change."
            )

        if test_command:
            test_command_section = f"Configured test command: {test_command}. Run it when practical and report the result."
        else:
            test_command_section = (
                "No configured test command is set; choose lightweight verification from the repo when practical."
            )

        build_command_section = ""
        if build_command:
            build_command_section = (
                f"Configured build command: {build_command}. Run it when practical before marking passed=true."
            )

        if review_only:
            execution_mode = (
                "This is a review-only fallback after the primary Code Tester run failed before producing a valid artifact. "
                "Do not invoke Playwright, CUA Driver, browsers, native GUI automation, or screen recording tools. "
                f"Primary failure notes: {fallback_reason}"
            )
        else:
            execution_mode = (
                "Run configured test/build commands when practical and complete an independent code review. "
                "Do not invoke Playwright, playwright-cli, cua-driver, browsers, or native GUI automation — UI Tester runs in the next stage."
            )

        framework = read_framework_conventions()
        framework_block = f"SpecForge framework rules:\n{framework}\n" if framework else ""

        return compose_stage_prompt(
            "code_tester",
            repo_root=repo_root,
            variables={
                "repo_root": str(repo_root),
                "docs_root": str(docs_root),
                "schema_hint": (
                    "{verify_report:string, passed:boolean, failure_notes?:string, "
                    "defects:[{severity:'P0'|'P1'|'P2', path?:string, owner?:'coder'|'code_tester'|'test_planner', message:string}], "
                    "ux_notes:[string], delivery_recommendations:[string], "
                    "adversarial_tests:[{path:'tests/adversarial/**', content:string}], "
                    "test_files:[{path:'tests/** except tests/adversarial/**', content:string}]}"
                ),
                "test_command_section": test_command_section,
                "build_command_section": build_command_section,
                "retry_notes_section": retry_notes_section,
                "framework_conventions": framework_block,
                "convention_excerpt": self._project_convention_prompt(repo_root),
                "context_manifest": self._context_manifest_prompt(
                    iteration_id,
                    FOR_TESTER,
                    heading="Required context files (read only these paths):",
                ),
                "runtime_notes": self._runtime_notes_prompt(iteration_id),
                "execution_mode": execution_mode,
            },
        )


    def _artifact_schema_inline(self, model: type[BaseModel]) -> str:
        return json.dumps(model.model_json_schema(), ensure_ascii=False)


    def _artifact_schema_file(self, iteration_id: str, name: str, model: type[BaseModel]) -> Path:
        schema_dir = self.project_root(iteration_id) / ".specforge" / "schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        path = schema_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


    def _project_field(self, state: PipelineState, field: str) -> Optional[str]:
        project_id = state.get("project_id")
        if not project_id:
            return None
        project = self.db.get_project_row(project_id)
        if project is None:
            return None
        return project[field]
