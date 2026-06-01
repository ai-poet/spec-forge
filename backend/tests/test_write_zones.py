from specforge.core.contracts import VerificationArtifact as VerificationArtifactModel
from specforge.policy.write_zones import owner_for_path, retry_target


def test_owner_for_path_zones():
    assert owner_for_path("src/main.py") == "coder"
    assert owner_for_path("tests/unit/foo.test.ts") == "test_planner"
    assert owner_for_path("tests/adversarial/edge.test.ts") == "code_tester"
    assert owner_for_path("prd.md") == "prd_planner"
    assert owner_for_path("verify_report.md") == "code_tester"


def test_retry_target_coder():
    artifact = VerificationArtifactModel(
        verify_report="# report",
        passed=False,
        defects=[
            {
                "severity": "P0",
                "path": "src/app.ts",
                "owner": "coder",
                "message": "bug",
            }
        ],
    )
    assert retry_target(artifact) == "coder"


def test_retry_target_code_tester():
    artifact = VerificationArtifactModel(
        verify_report="# report",
        passed=False,
        defects=[
            {
                "severity": "P0",
                "path": "tests/adversarial/x.test.ts",
                "owner": "code_tester",
                "message": "bad adversarial",
            }
        ],
    )
    assert retry_target(artifact) == "code_tester"


def test_retry_target_test_planner():
    artifact = VerificationArtifactModel(
        verify_report="# report",
        passed=False,
        defects=[
            {
                "severity": "P0",
                "path": "tests/unit/a.test.ts",
                "owner": "test_planner",
                "message": "protected test wrong",
            }
        ],
    )
    assert retry_target(artifact) == "test_planner"


def test_retry_target_gate_failure_notes():
    artifact = VerificationArtifactModel(
        verify_report="# report",
        passed=False,
        failure_notes="build failed after writing tests/adversarial/x.test.ts",
    )
    assert retry_target(artifact) == "code_tester"
