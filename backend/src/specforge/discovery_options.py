from __future__ import annotations

DISCOVERY_CUSTOM_OPTION_LABEL = "其他（请说明）"
MIN_DISCOVERY_PRESET_OPTIONS = 1


def normalize_discovery_options(options: list[str]) -> list[str]:
    """Ensure ask-turn options are non-empty with a custom-input choice last."""
    presets = [item.strip() for item in options if item and item.strip()]
    presets = [item for item in presets if item != DISCOVERY_CUSTOM_OPTION_LABEL]
    if len(presets) < MIN_DISCOVERY_PRESET_OPTIONS:
        raise ValueError(
            f"discovery ask requires at least {MIN_DISCOVERY_PRESET_OPTIONS} preset option "
            f"plus '{DISCOVERY_CUSTOM_OPTION_LABEL}'"
        )
    return [*presets, DISCOVERY_CUSTOM_OPTION_LABEL]


def is_discovery_custom_option(label: str) -> bool:
    return label.strip() == DISCOVERY_CUSTOM_OPTION_LABEL
