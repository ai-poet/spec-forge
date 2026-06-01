from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, Optional

from ...cli_commands import build_cli_command
from ...cli_runner import CLIResult
from ...contracts import (
    VerificationArtifact,
    UITestResult,
    UITestSpec,
    merge_cli_artifact_output,
    parse_json_artifact,
    validate_ui_spec_content,
)
from ...cua_bootstrap import CUA_INSTALL_HINT
from ...cua_session import cua_session_busy_message, read_cua_session_holder, try_acquire_cua_session
from ...docs_io import IterationDocs
from ...models import NodeName
from ...playwright_cli import PLAYWRIGHT_CLI_INSTALL_HINT, playwright_cli_wrapper
from ...prompt_loader import compose_stage_prompt

if TYPE_CHECKING:
    from ..state import PipelineState


class PipelineUiTesterMixin:
    """UI Tester CLI stage: playwright-cli (web) and cua-driver (native)."""

    def _run_ui_tester_agent(
        self,
        state: PipelineState,
        baseline: VerificationArtifact,
        docs: IterationDocs,
        specs: list[UITestSpec],
        *,
        run_id: Optional[str],
    ) -> tuple[VerificationArtifact, Optional[str]]:
        iteration_id = state["iteration_id"]
        cua_busy_holder: str | None = None
        if any(spec.kind == "native" for spec in specs):
            with try_acquire_cua_session(iteration_id) as session:
                if session is None:
                    holder = read_cua_session_holder()
                    cua_busy_holder = holder.iteration_id if holder else None

        if self._is_real_cli(state.get("mode")):
            self._reset_live_cli(iteration_id, NodeName.ui_tester.value)
            command = self._ui_tester_command(state, baseline=baseline, specs=specs, cua_busy_holder=cua_busy_holder)
            run_result = self._execute(state, command, node=NodeName.ui_tester.value)
            if self._is_iteration_gone(iteration_id):
                return baseline, run_id
            ui_run_id = self._record_run(iteration_id, NodeName.ui_tester.value, run_result)
            if run_result.returncode:
                parsed = self._try_ui_tester_artifact(state, run_result, baseline)
                if parsed is None:
                    raise ValueError(self._tester_failure_notes(run_result))
                artifact = parsed
            else:
                self._node_event(
                    iteration_id,
                    "node.progress",
                    NodeName.ui_tester.value,
                    "正在解析 UI 验证结果",
                    "已收到 UI Tester 输出。",
                    run_id=ui_run_id,
                )
                artifact = self._ui_tester_artifact(state, run_result, baseline)
            if cua_busy_holder:
                busy_msg = cua_session_busy_message(cua_busy_holder)
                if busy_msg not in artifact.ui_warnings:
                    artifact.ui_warnings.append(busy_msg)
                self._add_event(
                    iteration_id,
                    event_type="ui_tester.cua_busy",
                    payload={"holder": cua_busy_holder, "count": len(specs)},
                )
            return artifact, ui_run_id

        artifact = self._dry_run_ui_artifact(state, baseline, specs)
        if cua_busy_holder:
            artifact.ui_warnings.append(cua_session_busy_message(cua_busy_holder))
        return artifact, run_id

    def _ui_tester_command(
        self,
        state: PipelineState,
        *,
        baseline: VerificationArtifact,
        specs: list[UITestSpec],
        cua_busy_holder: str | None,
    ) -> list[str]:
        iteration_id = state["iteration_id"]
        if self._is_real_cli(state.get("mode")):
            prompt = self._ui_tester_prompt(state, baseline=baseline, specs=specs, cua_busy_holder=cua_busy_holder)
            provider = self._cli_provider(state, "ui_tester")
            return build_cli_command(
                provider=provider,
                prompt=prompt,
                schema_inline=self._artifact_schema_inline(VerificationArtifact),
                schema_file=self._artifact_schema_file(iteration_id, "ui_tester_artifact", VerificationArtifact),
            )
        return ["specforge", "ui_tester", iteration_id]

    def _ui_tester_prompt(
        self,
        state: PipelineState,
        *,
        baseline: VerificationArtifact,
        specs: list[UITestSpec],
        cua_busy_holder: str | None,
    ) -> str:
        iteration_id = state["iteration_id"]
        repo_root = self.project_repo_root(iteration_id)
        docs_root = self.docs_root(iteration_id)
        if cua_busy_holder:
            cua_session_section = (
                f"CuaDriver session is busy (held by {cua_busy_holder}). "
                "Mark native specs as warning if you cannot run cua-driver; do not steal user focus."
            )
        else:
            cua_session_section = "CuaDriver session: available for native specs when cua-driver is installed."

        return compose_stage_prompt(
            "ui_tester",
            repo_root=repo_root,
            variables={
                "repo_root": str(repo_root),
                "docs_root": str(docs_root),
                "schema_hint": (
                    "{verify_report:string, passed:boolean, failure_notes?:string, "
                    "defects:[{severity:'P0'|'P1'|'P2', path?:string, owner?:'coder'|'code_tester'|'test_planner'|'prd_planner', message:string}], "
                    "ux_notes:[string], delivery_recommendations:[string], "
                    "ui_results:[{id:string, title?:string, kind:'web'|'native', status:'passed'|'failed'|'warning'|'skipped', "
                    "target?:string, driver?:'playwright'|'cua', error?:string, observations:[string], "
                    "artifacts:[{label:string, path:string}]}], ui_warnings:[string], adversarial_tests:[{path:string, content:string}]}"
                ),
                "pwcli_wrapper": str(playwright_cli_wrapper()),
                "playwright_install_hint": PLAYWRIGHT_CLI_INSTALL_HINT,
                "cua_install_hint": CUA_INSTALL_HINT,
                "code_tester_artifact_json": json.dumps(baseline.model_dump(), ensure_ascii=False, indent=2),
                "ui_specs_section": self._ui_specs_prompt_section(specs),
                "cua_session_section": cua_session_section,
            },
        )

    def _ui_specs_prompt_section(self, specs: list[UITestSpec]) -> str:
        if not specs:
            return "(no tests/ui/*.json scenarios)"
        blocks: list[str] = []
        for spec in specs:
            blocks.append(
                f"### {spec.id} ({spec.kind})\n```json\n"
                f"{json.dumps(spec.model_dump(), ensure_ascii=False, indent=2)}\n```"
            )
        return "\n\n".join(blocks)

    def _ui_tester_artifact(
        self,
        state: PipelineState,
        run_result: CLIResult,
        baseline: VerificationArtifact,
    ) -> VerificationArtifact:
        if self._is_real_cli(state.get("mode")):
            raw = merge_cli_artifact_output(run_result.stdout, run_result.stderr)
            artifact = parse_json_artifact(raw, VerificationArtifact)  # type: ignore[assignment]
            return self._normalize_tester_artifact(artifact)
        return self._dry_run_ui_artifact(state, baseline, self._load_ui_specs(IterationDocs(self.docs_root(state["iteration_id"]))))

    def _try_ui_tester_artifact(
        self,
        state: PipelineState,
        run_result: CLIResult,
        baseline: VerificationArtifact,
    ) -> VerificationArtifact | None:
        try:
            return self._ui_tester_artifact(state, run_result, baseline)
        except Exception:
            return None

    def _dry_run_ui_artifact(
        self,
        state: PipelineState,
        baseline: VerificationArtifact,
        specs: list[UITestSpec],
    ) -> VerificationArtifact:
        artifact = VerificationArtifact.model_validate(baseline.model_dump())
        if not specs:
            return artifact
        results, warnings = self._dry_run_ui_results(state, specs)
        artifact.ui_results.extend(results)
        artifact.ui_warnings.extend(warnings)
        artifact.ux_notes.extend(self._ui_result_observations(results))
        return artifact

    def _dry_run_ui_results(self, state: PipelineState, specs: list[UITestSpec]) -> tuple[list[UITestResult], list[str]]:
        goal = (state.get("goal") or "").lower()
        warnings: list[str] = []
        results: list[UITestResult] = []
        for spec in specs:
            driver: Literal["playwright", "cua"] | None = "playwright" if spec.kind == "web" else "cua"
            target = spec.target.url or spec.target.bundle_id or spec.target.app_name or ""
            status: Literal["passed", "failed", "warning"] = "passed"
            error: str | None = None
            observations: list[str] = []
            if "ui fail" in goal:
                status = "failed"
                error = "dry-run simulated UI failure"
            elif "dual fail" in goal:
                status = "warning"
                observations.append("playwright-cli unavailable (dry-run)")
            elif ("ui mixed" in goal or "ui-mixed" in goal) and spec.kind == "native":
                status = "warning"
                observations.append("CuaDriver unavailable (dry-run)")
            elif "ui playwright" in goal and spec.kind == "web":
                observations.append("找到文本: SpecForge")
            elif status == "passed":
                observations.append(f"dry-run UI pass: {spec.id}")
            results.append(
                UITestResult(
                    id=spec.id,
                    title=spec.title,
                    kind=spec.kind,
                    status=status,
                    target=target,
                    driver=driver,
                    error=error,
                    observations=observations,
                )
            )
        if "dual fail" in goal:
            warnings.append("Playwright and CuaDriver unavailable (dry-run)")
        if ("ui mixed" in goal or "ui-mixed" in goal) and any(spec.kind == "native" for spec in specs):
            warnings.append("Native UI skipped: CuaDriver unavailable (dry-run)")
        return results, warnings

    def _ui_result_observations(self, results: list[UITestResult]) -> list[str]:
        observations: list[str] = []
        for result in results:
            driver = f" ({result.driver})" if result.driver else ""
            if result.status == "passed":
                observations.append(f"UI 验证通过{driver}: {result.title or result.id}")
            elif result.status == "failed":
                observations.append(f"UI 验证失败{driver}: {result.title or result.id} — {result.error or 'failed'}")
            elif result.status == "warning":
                observations.append(f"UI 未执行{driver}: {result.title or result.id}")
        return observations

    def _emit_ui_tester_result_events(
        self,
        iteration_id: str,
        artifact: VerificationArtifact,
        *,
        run_id: Optional[str],
    ) -> None:
        if not artifact.ui_results and not artifact.ui_warnings:
            return
        self._add_event(iteration_id, event_type="ui_tester.started", payload={"count": len(artifact.ui_results)})
        for warning in artifact.ui_warnings:
            self._add_event(iteration_id, event_type="ui_tester.warning", payload={"warning": warning})
            if "部分 UI 未执行" not in " ".join(artifact.delivery_recommendations):
                artifact.delivery_recommendations.append(f"部分 UI 未执行: {warning}")
        if artifact.ui_results:
            self._add_event(
                iteration_id,
                event_type="ui_tester.completed",
                payload={"count": len(artifact.ui_results)},
            )
        failed_results = [result for result in artifact.ui_results if result.status == "failed"]
        if failed_results:
            failed_summary = "; ".join(
                f"{result.title or result.id}: {result.error or 'failed'}" for result in failed_results
            )
            warning = f"UI 自动化测试失败，已降级为警告: {failed_summary}"
            if warning not in artifact.ui_warnings:
                artifact.ui_warnings.append(warning)
            if "UI 自动化存在失败项" not in " ".join(artifact.delivery_recommendations):
                artifact.delivery_recommendations.append(
                    "UI 自动化存在失败项；本轮是否通过以 Code Tester 代码审查未发现 P0/P1 缺陷为准，交付前建议人工复核失败 UI 场景。"
                )
            self._add_event(
                iteration_id,
                event_type="ui_tester.failed",
                payload={"failed": [result.model_dump() for result in failed_results], "blocking": False},
            )
            self._node_event(
                iteration_id,
                "node.progress",
                NodeName.ui_tester.value,
                "UI 验证需复核",
                "至少一条 UI 场景未通过，已作为非阻断警告记录。",
                severity="warning",
                action_hint="查看 UI 验证结果和 tests/ui/recordings；交付前建议人工复核。",
                run_id=run_id,
            )
        elif artifact.ui_results:
            self._node_event(
                iteration_id,
                "node.completed",
                NodeName.ui_tester.value,
                "UI 验证完成",
                f"已完成 {len(artifact.ui_results)} 条 UI 场景。",
                severity="success",
                run_id=run_id,
            )

    def _load_ui_specs(self, docs: IterationDocs) -> list[UITestSpec]:
        ui_root = docs.root / "tests" / "ui"
        if not ui_root.exists():
            return []
        specs: list[UITestSpec] = []
        for path in sorted(ui_root.glob("*.json")):
            content = path.read_text(encoding="utf-8")
            specs.append(validate_ui_spec_content(path.relative_to(docs.root).as_posix(), content))
        return specs
