from specforge.contracts import Defect
from specforge.contracts import TesterArtifact as TesterArtifactModel
from specforge.write_zones import (
    owner_for_path,
    owners_for_failure_notes,
    retry_target,
)


def test_owner_for_path_zones():
    assert owner_for_path("src/app.ts") == "coder"
    assert owner_for_path("internal/handler.go") == "coder"
    assert owner_for_path("tests/adversarial/edge.test.ts") == "tester"
    assert owner_for_path("tests/unit/foo.py") == "planner"
    assert owner_for_path("verify_report.md") == "tester"
    assert owner_for_path("system_design.md") == "planner"


def test_retry_target_tester_only_defects():
    artifact = TesterArtifactModel(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[
            Defect(
                severity="P0",
                path="tests/adversarial/bad.test.ts",
                owner="tester",
                message="wrong import depth",
            )
        ],
    )
    assert retry_target(artifact) == "tester"


def test_retry_target_coder_src_defect():
    artifact = TesterArtifactModel(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[
            Defect(severity="P0", path="src/api.ts", owner="coder", message="null deref"),
        ],
    )
    assert retry_target(artifact) == "coder"


def test_retry_target_inferred_from_failure_notes():
    artifact = TesterArtifactModel(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        failure_notes="tsc failed in tests/adversarial/foo.test.ts: cannot find module",
    )
    assert retry_target(artifact) == "tester"


def test_retry_target_blocked_for_protected_tests():
    owners = owners_for_failure_notes("modified protected test: tests/unit/a.py")
    assert "planner" in owners
    artifact = TesterArtifactModel(
        verify_report="# Report\n\n## Summary\n- Pass: 0\n- Fail: 1\n",
        passed=False,
        defects=[Defect(severity="P0", path="tests/unit/a.py", owner="planner", message="tampered")],
    )
    assert retry_target(artifact) == "blocked"
