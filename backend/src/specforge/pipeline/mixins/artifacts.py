from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ...agents.cli_runner import CLIResult
from ...core.contracts import (
    ArtifactFile,
    CodeTesterArtifact,
    CoderArtifact,
    ContextManifestEntry,
    Defect,
    PlannerClarificationArtifact,
    PlannerDiscoveryArtifact,
    PrdPlannerArtifact,
    TestPlannerArtifact,
    VerificationArtifact,
    UITestResult,
    merge_cli_artifact_output,
    parse_json_artifact,
    verification_from_code,
)
from ...core.models import IterationStatus, NodeName
from ...documents.docs_io import IterationDocs, compare_planning_integrity, compare_test_integrity, safe_relative_path
from ...policy.artifact_gate import run_project_commands
from ...policy.context_manifest import (
    ManifestLine,
    append_manifest_lines,
    resolve_coder_manifest,
    resolve_tester_manifest,
    write_jsonl,
)
from ...policy.write_zones import enrich_defects, retry_target, summarize_failure_notes
from ..state import PipelineState


class PipelineArtifactsMixin:

    def _planner_discovery_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerDiscoveryArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PlannerDiscoveryArtifact)  # type: ignore[return-value]
        discovery_qa = state.get("discovery_qa") or []
        goal = state["goal"]
        if not discovery_qa:
            return PlannerDiscoveryArtifact(
                status="ask",
                complexity="moderate",
                question=f"What is the primary acceptance criterion for: {goal}?",
                options=[
                    "Ship a minimal vertical slice first",
                    "Match existing product conventions exactly",
                    "Optimize for test coverage and CI gates",
                    "其他（请说明）",
                ],
                assumptions=["Dry-run discovery round 1"],
                requirements_brief=f"Goal: {goal}\n\n(Open questions remain.)",
                rationale="Dry-run asks one clarifying question before planning.",
            )
        return PlannerDiscoveryArtifact(
            status="ready",
            complexity="simple",
            assumptions=["User answered the dry-run discovery question"],
            requirements_brief=(
                f"Goal: {goal}\n\n"
                f"User answer: {discovery_qa[-1].get('answer', '')}\n\n"
                "Proceed to system design, modification plan, and protected tests."
            ),
            rationale="Dry-run discovery complete after one Q&A round.",
        )


    def _prd_planner_artifact(self, state: PipelineState, run_result: CLIResult) -> PrdPlannerArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PrdPlannerArtifact)  # type: ignore[return-value]
        goal = state["goal"]
        prd = f"""---\ndoc: prd\niteration: 1\nstatus: draft\nowner: prd_planner\n---\n\n# Iteration 1 - PRD\n\nGoal: {goal}\n\n## Scope\nDry-run PRD from prd_planner.\n\n## Acceptance criteria\n- Generate a minimal source module that satisfies test_planner protected tests.\n"""
        return PrdPlannerArtifact(
            prd=prd,
            context_for_coder=[
                ContextManifestEntry(file="prd.md", reason="Approved PRD for Coder"),
            ],
            context_for_tester=[
                ContextManifestEntry(file="prd.md", reason="Product intent for verification"),
            ],
        )


    def _test_planner_artifact(self, state: PipelineState, run_result: CLIResult) -> TestPlannerArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, TestPlannerArtifact)  # type: ignore[return-value]
        return TestPlannerArtifact(
            testing_plan="""---\ndoc: testing_plan\niteration: 1\nstatus: draft\nowner: test_planner\n---\n\n# Iteration 1 - Testing Plan\n\n- T01: dry-run reaches delivery approval.\n""",
        )


    def _planner_clarification_artifact(self, state: PipelineState, run_result: CLIResult) -> PlannerClarificationArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, PlannerClarificationArtifact)  # type: ignore[return-value]
        request = state.get("clarification_request") or "unspecified clarification"
        return PlannerClarificationArtifact(
            answer=f"Proceed with the approved spec. Clarification resolved: {request}",
            summary="Dry-run planner clarification answered the coder request.",
        )


    def _coder_artifact(self, state: PipelineState, run_result: CLIResult) -> CoderArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            return parse_json_artifact(raw, CoderArtifact)  # type: ignore[return-value]
        return CoderArtifact(changed_paths=["src/app.py"], summary="dry-run source module generated")


    def _code_tester_artifact(self, state: PipelineState, run_result: CLIResult) -> CodeTesterArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            artifact = parse_json_artifact(raw, CodeTesterArtifact)  # type: ignore[assignment]
            return self._normalize_code_tester_artifact(artifact)
        tester = self._dry_run_tester_artifact(state)
        return CodeTesterArtifact.model_validate(tester.model_dump(exclude={"ui_results", "ui_warnings"}))


    def _dry_run_tester_artifact(self, state: PipelineState) -> VerificationArtifact:
        if "force tester failure" in state.get("goal", ""):
            return VerificationArtifact(
                verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 0\n- Fail: 3\n""",
                passed=False,
                failure_notes="forced tester failure",
                ux_notes=["验证未通过，暂不建议从用户体验角度验收。"],
                delivery_recommendations=["先修复失败测试，再重新进行交付评审。"],
            )
        return VerificationArtifact(
            verify_report="""---\ndoc: verify_report\niteration: 1\nstatus: draft\nowner: node3\n---\n\n# Iteration 1 - Verify Report\n\n## Summary\n- Tests in plan: 3\n- Tests executed: 3\n- Pass: 3\n- Fail: 0\n\n## LangGraph\nThe tester node completed and paused for verify approval.\n\n## 用户体验观察\n- dry-run 流程可以从设计审批推进到验证审批，核心状态对用户可见。\n\n## 交付建议\n- 本轮可以交付；后续建议补充真实 CLI 和浏览器级验收。\n""",
            passed=True,
            ux_notes=["核心流程状态清晰，可被人工审批节点接住。"],
            delivery_recommendations=["本轮可以交付；下一步建议补充真实 CLI smoke test。"],
        )


    def _try_code_tester_artifact(self, state: PipelineState, run_result: CLIResult) -> CodeTesterArtifact | None:
        try:
            return self._code_tester_artifact(state, run_result)
        except Exception:
            return None


    def _normalize_code_tester_artifact(self, artifact: CodeTesterArtifact) -> CodeTesterArtifact:
        tester = self._normalize_tester_artifact(verification_from_code(artifact))
        return CodeTesterArtifact.model_validate(tester.model_dump(exclude={"ui_results", "ui_warnings"}))


    def _augment_review_fallback_artifact(self, artifact: VerificationArtifact, primary_notes: str) -> None:
        compact_notes = self._compact_failure_notes(primary_notes)
        warning = f"主 Tester 自动化未完成，已改用代码审查兜底: {compact_notes}"
        if warning not in artifact.ui_warnings:
            artifact.ui_warnings.append(warning)
        recommendation = "自动化 UI 验证未完整执行；交付前建议在具备 Playwright/CUA 环境时补跑 UI trajectory。"
        if recommendation not in artifact.delivery_recommendations:
            artifact.delivery_recommendations.append(recommendation)


    def _tester_failure_notes(self, *results: CLIResult) -> str:
        notes: list[str] = []
        for index, result in enumerate(results, start=1):
            text = merge_cli_artifact_output(result.stdout, result.stderr)
            label = "primary" if index == 1 else f"fallback {index - 1}"
            if text.strip():
                notes.append(f"{label}: {self._compact_failure_notes(text)}")
            else:
                notes.append(f"{label}: exit code {result.returncode}")
        return "; ".join(notes)


    def _compact_failure_notes(self, text: str, limit: int = 600) -> str:
        compact = " ".join(text.split())
        if not compact:
            return "no diagnostic output"
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."


    def _write_prd_planner_artifact(self, iteration_id: str, docs: IterationDocs, artifact: PrdPlannerArtifact, *, run_id: Optional[str] = None) -> None:
        path = docs.write_text("prd.md", artifact.prd)
        self._record_document(iteration_id, "prd", path)
        self._node_event(iteration_id, "artifact.created", NodeName.prd_planner.value, "PRD 已生成", "prd.md 已写入 iteration 文档目录。", severity="success", document="prd", run_id=run_id)
        context_root = docs.root / "context"
        write_jsonl(context_root / "for_coder.jsonl", resolve_coder_manifest(artifact))
        write_jsonl(context_root / "for_tester.jsonl", resolve_tester_manifest(artifact))
        self._record_document(iteration_id, "context/for_coder.jsonl", context_root / "for_coder.jsonl")
        self._record_document(iteration_id, "context/for_tester.jsonl", context_root / "for_tester.jsonl")


    def _write_test_planner_artifact(self, iteration_id: str, docs: IterationDocs, artifact: TestPlannerArtifact, *, run_id: Optional[str] = None) -> None:
        plan_path = docs.write_text("testing_plan.md", artifact.testing_plan)
        self._record_document(iteration_id, "testing_plan", plan_path)
        self._node_event(iteration_id, "artifact.created", NodeName.test_planner.value, "测试计划已生成", "testing_plan.md 已写入。", severity="success", document="testing_plan", run_id=run_id)
        test_lines: list[ManifestLine] = [
            ManifestLine(file="testing_plan.md", reason="Test strategy for Code Tester"),
        ]
        context_root = docs.root / "context"
        append_manifest_lines(context_root / "for_coder.jsonl", test_lines)
        append_manifest_lines(context_root / "for_tester.jsonl", test_lines)


    def _ensure_verify_report_markers(self, text: str) -> str:
        result = text if text.strip() else "# Verify Report\n\n"
        if "# " not in result:
            result = f"# Verify Report\n\n{result.lstrip()}"
        if "Pass" not in result:
            if "## Summary" in result:
                suffix = "" if result.endswith("\n") else "\n"
                result = f"{result}{suffix}- Pass: 0\n- Fail: 0\n"
            else:
                result = f"{result.rstrip()}\n\n## Summary\n- Pass: 0\n- Fail: 0\n"
        return result


    def _write_tester_artifact(self, iteration_id: str, docs: IterationDocs, artifact: VerificationArtifact, *, run_id: Optional[str] = None) -> None:
        artifact = VerificationArtifact.model_validate(artifact.model_dump())
        artifact = self._normalize_tester_file_zones(iteration_id, artifact, run_id=run_id)
        verify_report = self._ensure_verify_report_markers(artifact.verify_report)
        verify = docs.write_text("verify_report.md", verify_report)
        self._record_document(iteration_id, "verify_report", verify)
        self._node_event(iteration_id, "artifact.created", NodeName.code_tester.value, "验证报告已生成", "verify_report 已写入 iteration 文档目录。", severity="success", document="verify_report", run_id=run_id)
        if artifact.ui_results or artifact.ui_warnings:
            ui_json = docs.write_text(
                "ui_results.json",
                json.dumps(
                    {
                        "warnings": artifact.ui_warnings,
                        "results": [result.model_dump() for result in artifact.ui_results],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self._record_document(iteration_id, "ui_results", ui_json)
            ui_report = docs.write_text("ui_report.md", self._ui_report_markdown(artifact))
            self._record_document(iteration_id, "ui_report", ui_report)
            self._node_event(iteration_id, "artifact.created", NodeName.ui_tester.value, "UI 验证产物已生成", "ui_results 和 ui_report 已写入 iteration 文档目录。", severity="success", document="ui_report", run_id=run_id)
        advice = self._delivery_advice_markdown(artifact)
        if advice:
            advice_path = docs.write_text("delivery_advice.md", advice)
            self._record_document(iteration_id, "delivery_advice", advice_path)
            self._node_event(iteration_id, "artifact.created", NodeName.code_tester.value, "交付建议已生成", "delivery_advice 已写入 iteration 文档目录。", severity="success", document="delivery_advice", run_id=run_id)
            self._add_event(
                iteration_id,
                event_type="code_tester.delivery_advice",
                payload={"ux_notes": artifact.ux_notes, "delivery_recommendations": artifact.delivery_recommendations},
            )
        for file in artifact.test_files:
            relative = safe_relative_path(file.path)
            if not relative.parts or relative.parts[0] != "tests" or (len(relative.parts) > 1 and relative.parts[1] == "adversarial"):
                raise ValueError(f"tester test_files path not allowed: {file.path}")
            if len(relative.parts) >= 2 and relative.parts[:2] == ("tests", "ui"):
                raise ValueError(f"tests/ui artifacts are no longer generated: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)
            self._node_event(iteration_id, "artifact.created", NodeName.code_tester.value, "测试文件已生成", relative.as_posix(), severity="success", document=relative.as_posix(), run_id=run_id)
        for file in artifact.adversarial_tests:
            relative = safe_relative_path(file.path)
            if relative.parts[:2] != ("tests", "adversarial"):
                raise ValueError(f"tester adversarial path not allowed: {file.path}")
            path = docs.write_text(relative.as_posix(), file.content)
            self._record_document(iteration_id, relative.as_posix(), path)
            self._node_event(iteration_id, "artifact.created", NodeName.code_tester.value, "对抗测试已生成", relative.as_posix(), severity="success", document=relative.as_posix(), run_id=run_id)


    def _normalize_tester_file_zones(self, iteration_id: str, artifact: VerificationArtifact, *, run_id: Optional[str] = None) -> VerificationArtifact:
        misplaced: list[ArtifactFile] = []
        remaining: list[ArtifactFile] = []
        for file in artifact.test_files:
            try:
                relative = safe_relative_path(file.path)
            except ValueError:
                remaining.append(file)
                continue
            if relative.parts[:2] == ("tests", "adversarial"):
                misplaced.append(file)
            else:
                remaining.append(file)
        if not misplaced:
            return artifact

        adversarial_by_path = {file.path: file for file in artifact.adversarial_tests}
        for file in misplaced:
            adversarial_by_path[file.path] = file
        moved_paths = [file.path for file in misplaced]
        self._add_event(
            iteration_id,
            event_type="code_tester.artifact_normalized",
            payload={"moved_to_adversarial_tests": moved_paths, "run_id": run_id},
        )
        self._node_event(
            iteration_id,
            "node.progress",
            NodeName.code_tester.value,
            "Tester 产物已自动归位",
            "已将 tests/adversarial/** 从 test_files 移至 adversarial_tests。",
            severity="warning",
            run_id=run_id,
            action_hint="后续 Code Tester 应把 tests/adversarial/** 放入 adversarial_tests 字段。",
        )
        return artifact.model_copy(
            update={
                "test_files": remaining,
                "adversarial_tests": list(adversarial_by_path.values()),
            }
        )


    def _ui_report_markdown(self, artifact: VerificationArtifact) -> str:
        total = len(artifact.ui_results)
        passed = sum(1 for result in artifact.ui_results if result.status == "passed")
        failed = sum(1 for result in artifact.ui_results if result.status == "failed")
        warnings = sum(1 for result in artifact.ui_results if result.status == "warning") + len(artifact.ui_warnings)
        rows = []
        for result in artifact.ui_results:
            error = result.error or ""
            driver = result.driver or "-"
            rows.append(f"| {result.id} | {result.kind} | {result.target} | {driver} | {result.status} | {error} |")
        warning_lines = "\n".join(f"- {warning}" for warning in artifact.ui_warnings) or "- 无"
        return (
            "---\n"
            "doc: ui_report\n"
            "status: draft\n"
            "owner: node3\n"
            "---\n\n"
            "# UI Driver 验证报告\n\n"
            "## 摘要\n"
            f"- UI 测试数量: {total}\n"
            f"- 通过: {passed}\n"
            f"- 失败: {failed}\n"
            f"- 未执行: {warnings}\n\n"
            "## 结果\n"
            "| ID | 类型 | 目标 | Driver | 状态 | 错误 |\n"
            "|---|---|---|---|---|---|\n"
            f"{chr(10).join(rows) if rows else '| - | - | - | - | - | - |'}\n\n"
            "## 未执行 / 回退说明\n"
            f"{warning_lines}\n"
        )


    def _delivery_advice_markdown(self, artifact: VerificationArtifact) -> str:
        if not artifact.ux_notes and not artifact.delivery_recommendations:
            return ""
        ux = "\n".join(f"- {item}" for item in artifact.ux_notes) or "- 暂无"
        recommendations = "\n".join(f"- {item}" for item in artifact.delivery_recommendations) or "- 暂无"
        return (
            "---\n"
            "doc: delivery_advice\n"
            "status: draft\n"
            "owner: node3\n"
            "---\n\n"
            "# 交付建议\n\n"
            "## 用户体验观察\n"
            f"{ux}\n\n"
            "## 后续建议\n"
            f"{recommendations}\n"
        )


    def _integrity_problems(self, iteration_id: str) -> list[str]:
        row = self._require_iteration(iteration_id)
        baseline = self._json(row["test_integrity_baseline"], {})
        return compare_test_integrity(self.docs_root(iteration_id), baseline)


    def _planning_integrity_problems(self, iteration_id: str) -> list[str]:
        row = self._require_iteration(iteration_id)
        baseline = self._json(
            row["planning_integrity_baseline"] if "planning_integrity_baseline" in row.keys() else "{}",
            {},
        )
        if not baseline:
            return []
        return compare_planning_integrity(self.docs_root(iteration_id), baseline)


    def _planning_integrity_failure(
        self,
        iteration_id: str,
        *,
        node: str,
        run_id: Optional[str] = None,
        action_hint: Optional[str] = None,
    ) -> PipelineState | None:
        problems = self._planning_integrity_problems(iteration_id)
        if not problems:
            return None
        message = "; ".join(problems)
        self._node_event(
            iteration_id,
            "node.failed",
            node,
            "规划文档完整性失败",
            message,
            severity="error",
            run_id=run_id,
            action_hint=action_hint or "检查 PRD、testing_plan 与 context manifests 是否被非规划节点修改。",
        )
        return self._block(iteration_id, "planning_integrity.failed", run_id, message)


    def _normalize_tester_artifact(self, artifact: VerificationArtifact) -> VerificationArtifact:
        defects = enrich_defects(artifact)
        failure_notes = summarize_failure_notes(artifact) if defects else artifact.failure_notes
        return artifact.model_copy(update={"defects": defects, "failure_notes": failure_notes})


    def _gate_failed_artifact(self, artifact: VerificationArtifact, gate_msg: str) -> VerificationArtifact:
        defect = Defect(severity="P0", owner="coder", message=gate_msg)
        defects = [*artifact.defects, defect] if artifact.defects else [defect]
        return artifact.model_copy(update={"passed": False, "defects": defects, "failure_notes": gate_msg})


    def _run_artifact_gate(self, state: PipelineState) -> tuple[bool, str]:
        iteration_id = state["iteration_id"]
        row = self._require_iteration(iteration_id)
        test_command = row["test_command"] if "test_command" in row.keys() else None
        build_command = row["build_command"] if "build_command" in row.keys() else None
        if not build_command:
            build_command = self._project_field(state, "default_build_command")
        if not test_command and not build_command:
            return True, ""
        return run_project_commands(
            self.project_repo_root(iteration_id),
            build_command=build_command,
            test_command=test_command,
        )


    def _rollback_tester_adversarial(self, iteration_id: str, adversarial_tests: list[ArtifactFile]) -> None:
        docs_root = self.docs_root(iteration_id)
        for file in adversarial_tests:
            relative = safe_relative_path(file.path)
            path = docs_root / relative
            if path.exists():
                path.unlink()


    def _route_tester_failure(self, state: PipelineState, run_id: str, artifact: VerificationArtifact) -> PipelineState:
        iteration_id = state["iteration_id"]
        artifact = self._normalize_tester_artifact(artifact)
        target = retry_target(artifact)
        notes = artifact.failure_notes or summarize_failure_notes(artifact)

        if target == "blocked":
            self._node_event(
                iteration_id,
                "node.failed",
                NodeName.code_tester.value,
                "验证失败涉及 PRD 范围",
                notes,
                severity="error",
                run_id=run_id,
                action_hint="PRD 范围问题需要人工介入。",
            )
            return self._block(iteration_id, "code_tester.protected_test_failure", run_id, notes)

        if target == "test_planner":
            retry_counts = self._increment_count(state, "test_planner_self")
            max_retries = state.get("max_tester_self_retries", 3)
            if retry_counts["test_planner_self"] > max_retries:
                self._update_iteration(iteration_id, retry_counts=retry_counts)
                return self._block(iteration_id, "test_planner.self_max_retries", run_id, notes)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.planning.value,
                current_node=None,
                retry_counts=retry_counts,
                last_error=notes,
            )
            self._add_event(
                iteration_id,
                event_type="test_planner.retry",
                payload={"run_id": run_id, "notes": notes, "count": retry_counts["test_planner_self"]},
            )
            self._node_event(
                iteration_id,
                "node.progress",
                NodeName.test_planner.value,
                "受保护测试需修订",
                notes,
                severity="warning",
                run_id=run_id,
            )
            return {
                "route": "test_planner_retry",
                "failure_notes": notes,
                "retry_target": "test_planner",
                "retry_counts": retry_counts,
                "pending_code_tester_json": None,
            }

        if target == "code_tester":
            retry_counts = self._increment_count(state, "code_tester_self")
            max_retries = state.get("max_tester_self_retries", 3)
            if retry_counts["code_tester_self"] > max_retries:
                self._update_iteration(iteration_id, retry_counts=retry_counts)
                return self._block(iteration_id, "code_tester.self_max_retries", run_id, notes)
            self._update_iteration(
                iteration_id,
                status=IterationStatus.retrying.value,
                current_node=None,
                retry_counts=retry_counts,
                last_error=notes,
            )
            self._add_event(
                iteration_id,
                event_type="code_tester.retry_to_self",
                payload={"run_id": run_id, "notes": notes, "count": retry_counts["code_tester_self"], "retry_target": "code_tester"},
            )
            self._node_event(
                iteration_id,
                "node.progress",
                NodeName.code_tester.value,
                "验证产物不合格，Code Tester 自修",
                notes,
                severity="warning",
                run_id=run_id,
            )
            return {
                "route": "self_retry",
                "failure_notes": notes,
                "retry_target": "code_tester",
                "retry_counts": retry_counts,
                "code_tester_run_id": run_id,
                "pending_code_tester_json": None,
            }

        retry_counts = self._increment_count(state, "coder_tester")
        if retry_counts["coder_tester"] > state.get("max_coder_tester_retries", 5):
            self._update_iteration(iteration_id, retry_counts=retry_counts)
            return self._block(iteration_id, "code_tester.max_retries", run_id, notes)
        self._update_iteration(
            iteration_id,
            status=IterationStatus.retrying.value,
            current_node=None,
            retry_counts=retry_counts,
            last_error=notes,
        )
        self._add_event(
            iteration_id,
            event_type="code_tester.retry_to_coder",
            payload={"run_id": run_id, "notes": notes, "count": retry_counts["coder_tester"], "retry_target": "coder"},
        )
        self._node_event(
            iteration_id,
            "node.progress",
            NodeName.code_tester.value,
            "验证失败，回到实现节点",
            notes,
            severity="warning",
            run_id=run_id,
            action_hint=f"缺陷落在 Coder 写区；第 {retry_counts['coder_tester']} 次实现/验证重试。",
        )
        return {
            "route": "retry",
            "failure_notes": notes,
            "retry_target": "coder",
            "retry_counts": retry_counts,
            "code_tester_run_id": run_id,
            "pending_code_tester_json": None,
        }


    def _tester_retry_or_block(self, state: PipelineState, run_id: str, notes: str) -> PipelineState:
        artifact = VerificationArtifact(
            verify_report="# Verify Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
            passed=False,
            failure_notes=notes,
        )
        return self._route_tester_failure(state, run_id, artifact)


    def _increment_count(self, state: PipelineState, key: str) -> dict[str, int]:
        counts = dict(state.get("retry_counts") or {})
        counts[key] = counts.get(key, 0) + 1
        return counts


    def _json(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default


    def _ui_results(self, iteration_id: str) -> list[UITestResult]:
        path = self.docs_root(iteration_id) / "ui_results.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_results = payload.get("results", []) if isinstance(payload, dict) else []
            return [UITestResult.model_validate(item) for item in raw_results]
        except Exception:
            return []
