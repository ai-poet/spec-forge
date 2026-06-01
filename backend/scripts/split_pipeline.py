#!/usr/bin/env python3
"""One-off: split pipeline/orchestrator.py into mixins, routes, graph, nodes."""
from __future__ import annotations

import ast
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1] / "src" / "specforge" / "pipeline"
ORCH = PIPELINE_DIR / "orchestrator.py"

RUNTIME_METHODS = [
    "_live_cli_snapshot", "_reset_live_cli", "_append_live_cli", "_clear_live_cli",
    "_maybe_publish_cli_output", "_maybe_publish_live_cli",
    "_config", "_begin_invoke", "_end_invoke", "_format_cli_failure",
    "_require_iteration", "_is_iteration_gone", "_abort_state", "_record_run",
    "_record_document", "_update_iteration", "_add_event", "_publish_snapshot", "_block",
    "_execute", "_cli_display_event", "_is_real_cli", "_execution_cwd",
    "_node_event", "_error_title", "_error_action_hint",
]
ROUTES_METHODS = [
    "_route_after_discovery", "_route_after_prd_planner", "_route_after_test_planner",
    "_route_after_coder", "_route_after_clarification", "_route_after_integrity",
    "_route_after_code_tester", "_route_after_ui_tester", "_route_after_planner_verify",
]
GRAPH_METHODS = ["_build_graph"]
PROMPTS_METHODS = [
    "_workflow_state_section", "_context_manifest_prompt", "_runtime_notes_prompt",
    "_project_convention_prompt", "_spec_index_prompt", "_planner_brief",
    "_discovery_context_prompt", "_format_discovery_qa_for_prompt",
    "_synthesize_requirements_brief", "_discovery_brief_markdown", "_discovery_snapshot_fields",
    "_cli_provider", "_planner_discovery_command", "_prd_planner_command", "_test_planner_command",
    "_planner_clarification_command", "_coder_command", "_code_tester_command", "_code_tester_prompt",
    "_artifact_schema_inline", "_artifact_schema_file", "_project_field",
]
ARTIFACTS_METHODS = [
    "_planner_discovery_artifact", "_prd_planner_artifact", "_test_planner_artifact",
    "_planner_clarification_artifact", "_coder_artifact", "_code_tester_artifact",
    "_dry_run_tester_artifact", "_try_code_tester_artifact", "_normalize_code_tester_artifact",
    "_augment_review_fallback_artifact", "_tester_failure_notes", "_compact_failure_notes",
    "_write_prd_planner_artifact", "_write_test_planner_artifact", "_ensure_verify_report_markers",
    "_write_tester_artifact", "_ui_report_markdown", "_delivery_advice_markdown",
    "_integrity_problems", "_normalize_tester_artifact", "_gate_failed_artifact",
    "_run_artifact_gate", "_rollback_tester_adversarial", "_route_tester_failure",
    "_tester_retry_or_block", "_increment_count", "_json", "_ui_results",
]
PLANNING_METHODS = [
    "_planner_discovery_node", "_requirements_input_node", "_prd_planner_node", "_test_planner_node",
]
IMPL_METHODS = ["_coder_node", "_planner_clarification_node", "_integrity_check_node"]
VERIFY_METHODS = [
    "_code_tester_node", "_ui_tester_node", "_planner_verify_node", "_verify_approval_node", "_done_node",
]
KEEP_METHODS = {
    "__init__", "project_repo_root", "project_root", "docs_root", "_prepare_iteration_docs",
    "start", "_build_state", "answer_requirements", "skip_discovery", "approve_verify",
    "resume", "can_resume", "cancel_cli", "stop_iteration", "can_resume_stopped", "resume_stopped",
    "_stopped_resume_node", "_infer_node_from_status", "_status_for_node", "retry", "fail_job",
    "dashboard_snapshot", "add_runtime_note",
}

HEADERS = {
    "mixins/runtime.py": '''from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ...cli_event_presenter import CliDisplayEvent
from ...cli_runner import CLIResult
from ...db import iso, utcnow
from ...events import EventEnvelope
from ...models import IterationStatus, Mode

if TYPE_CHECKING:
    from ..state import PipelineState


class PipelineRuntimeMixin:
''',
    "mixins/prompts.py": '''from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel

from ...artifact_gate import read_convention_excerpt, read_framework_conventions, read_spec_index
from ...cli_commands import CliStage, build_cli_command, parse_cli_bindings, resolve_cli_provider
from ...context_manifest import FOR_CODER, FOR_TESTER, format_manifest_for_prompt, format_runtime_notes_section
from ...contracts import (
    CodeTesterArtifact,
    CoderArtifact,
    PlannerClarificationArtifact,
    PlannerDiscoveryArtifact,
    PrdPlannerArtifact,
    TestPlannerArtifact,
    UI_TEST_ACTIONS,
)
from ...models import NodeName
from ...prompt_loader import compose_stage_prompt

if TYPE_CHECKING:
    from ..state import PipelineState


class PipelinePromptsMixin:
''',
    "mixins/artifacts.py": '''from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ...artifact_gate import run_project_commands
from ...cli_runner import CLIResult
from ...contracts import (
    ArtifactFile,
    CodeTesterArtifact,
    CoderArtifact,
    PlannerClarificationArtifact,
    PlannerDiscoveryArtifact,
    PrdPlannerArtifact,
    TestPlannerArtifact,
    VerificationArtifact,
    UITestResult,
    merge_cli_artifact_output,
    parse_json_artifact,
    verification_from_code,
    validate_ui_spec_content,
)
from ...docs_io import IterationDocs, compare_test_integrity, safe_relative_path
from ...models import IterationStatus, NodeName
from ...write_zones import enrich_defects, retry_target, summarize_failure_notes
from ...contracts import Defect

if TYPE_CHECKING:
    from ..state import PipelineState


class PipelineArtifactsMixin:
''',
    "routes.py": '''from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .state import PipelineState


class PipelineRoutesMixin:
''',
    "graph.py": '''from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..state import PipelineState


class PipelineGraphMixin:
''',
    "nodes/planning.py": '''from __future__ import annotations

from typing import TYPE_CHECKING

from ...models import IterationStatus, NodeName

if TYPE_CHECKING:
    from ..state import PipelineState


class PlanningNodesMixin:
''',
    "nodes/implementation.py": '''from __future__ import annotations

from typing import TYPE_CHECKING

from ...models import IterationStatus, NodeName

if TYPE_CHECKING:
    from ..state import PipelineState


class ImplementationNodesMixin:
''',
    "nodes/verification.py": '''from __future__ import annotations

from typing import TYPE_CHECKING

from ...models import IterationStatus, NodeName

if TYPE_CHECKING:
    from ..state import PipelineState


class VerificationNodesMixin:
''',
}

ORCH_HEADER = '''from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from ..cli_runner import BaseRunner, DryRunRunner, RealCLIRunner
from ..cli_event_presenter import CliEventPresenter
from ..config import settings
from ..db import Database
from ..docs_io import IterationDocs
from ..docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root
from ..events import EventBroker
from ..context_manifest import append_runtime_note
from ..models import IterationStatus, Mode, NodeName

from .graph import PipelineGraphMixin
from .mixins.artifacts import PipelineArtifactsMixin
from .mixins.prompts import PipelinePromptsMixin
from .mixins.runtime import PipelineRuntimeMixin
from .mixins.ui_tester import PipelineUiTesterMixin
from .nodes.implementation import ImplementationNodesMixin
from .nodes.planning import PlanningNodesMixin
from .nodes.verification import VerificationNodesMixin
from .routes import PipelineRoutesMixin
from .state import PipelineState


class LangGraphPipeline(
    PlanningNodesMixin,
    ImplementationNodesMixin,
    VerificationNodesMixin,
    PipelineUiTesterMixin,
    PipelineArtifactsMixin,
    PipelinePromptsMixin,
    PipelineRoutesMixin,
    PipelineGraphMixin,
    PipelineRuntimeMixin,
):
'''


def main() -> None:
    source = ORCH.read_text()
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LangGraphPipeline")

    def src(name: str) -> str:
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                return "".join(lines[item.lineno - 1 : item.end_lineno])
        raise KeyError(name)

    def order(names: list[str]) -> list[str]:
        order_map = {item.name: item.lineno for item in class_node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return sorted(names, key=lambda n: order_map[n])

    outputs: dict[str, list[str]] = {
        "mixins/runtime.py": RUNTIME_METHODS,
        "mixins/prompts.py": PROMPTS_METHODS,
        "mixins/artifacts.py": ARTIFACTS_METHODS,
        "routes.py": ROUTES_METHODS,
        "graph.py": GRAPH_METHODS,
        "nodes/planning.py": PLANNING_METHODS,
        "nodes/implementation.py": IMPL_METHODS,
        "nodes/verification.py": VERIFY_METHODS,
    }
    extracted: set[str] = set()
    for rel, names in outputs.items():
        path = PIPELINE_DIR / rel
        body = [HEADERS[rel]]
        for name in order(names):
            body.append(src(name))
            body.append("")
            extracted.add(name)
        path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        print(f"wrote {rel} ({len(names)} methods)")

    keep_parts = [ORCH_HEADER]
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in KEEP_METHODS:
            keep_parts.append(src(item.name))
            keep_parts.append("")
    ORCH.write_text("\n".join(keep_parts).rstrip() + "\n", encoding="utf-8")
    print(f"wrote orchestrator.py ({len(KEEP_METHODS)} methods)")

    all_methods = {item.name for item in class_node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = all_methods - extracted - KEEP_METHODS
    if missing:
        raise SystemExit(f"unassigned methods: {sorted(missing)}")


if __name__ == "__main__":
    main()
