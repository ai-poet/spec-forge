import pytest

from specforge.core.contracts import PlannerDiscoveryArtifact
from specforge.policy.discovery_options import DISCOVERY_CUSTOM_OPTION_LABEL, normalize_discovery_options


def test_normalize_discovery_options_appends_custom_last():
    result = normalize_discovery_options(["Option A", "Option B"])
    assert result == ["Option A", "Option B", DISCOVERY_CUSTOM_OPTION_LABEL]


def test_normalize_discovery_options_dedupes_custom():
    result = normalize_discovery_options(["A", DISCOVERY_CUSTOM_OPTION_LABEL, "B"])
    assert result == ["A", "B", DISCOVERY_CUSTOM_OPTION_LABEL]


def test_normalize_discovery_options_requires_preset():
    with pytest.raises(ValueError, match="at least"):
        normalize_discovery_options([DISCOVERY_CUSTOM_OPTION_LABEL])


def test_planner_discovery_artifact_validates_ask_options():
    artifact = PlannerDiscoveryArtifact(
        status="ask",
        question="Which scope?",
        options=["MVP first", "Full feature"],
    )
    assert artifact.options[-1] == DISCOVERY_CUSTOM_OPTION_LABEL
