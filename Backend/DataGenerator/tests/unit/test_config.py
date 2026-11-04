# Config loading, overrides and cross-file reference checks
from __future__ import annotations

import pytest
from orggraph_dataset.config import (
    ConfigError,
    OrgGraphConfig,
    apply_overrides,
    build_config,
    load_raw_config,
    parse_override_pairs,
)

from tests.conftest import CONFIG_DIR


def test_default_config_loads(config: OrgGraphConfig) -> None:
    assert len(config.industries.industries) == 19
    assert set(config.noise.profiles) >= {
        "clean",
        "low_noise",
        "medium_noise",
        "high_noise",
        "enterprise_complexity",
    }
    assert len(config.archetypes.archetypes) == 7
    assert config.company_sizes.segments["small"].min == 100


def test_archetype_defaults_are_merged(config: OrgGraphConfig) -> None:
    functional = config.archetypes.archetypes["functional"]
    flat = config.archetypes.archetypes["flat_startup"]
    assert functional.levels == ["manager", "senior_manager", "director", "senior_director", "vp", "svp"]
    assert flat.levels == ["manager", "director", "vp"]
    assert flat.level_size_scale < functional.level_size_scale


def test_override_pairs_are_parsed_as_yaml() -> None:
    parsed = parse_override_pairs(["dataset.seed=7", "dataset.splits.holdout_industries=[media]"])
    assert parsed == {"dataset.seed": 7, "dataset.splits.holdout_industries": ["media"]}


def test_override_applies_and_validates() -> None:
    _, raw = load_raw_config(CONFIG_DIR)
    cfg = build_config(apply_overrides(raw, {"dataset.workforce.remote_probability": 0.5}))
    assert cfg.dataset.workforce.remote_probability == 0.5


def test_unknown_override_path_fails() -> None:
    _, raw = load_raw_config(CONFIG_DIR)
    with pytest.raises(ConfigError, match="does not exist"):
        apply_overrides(raw, {"dataset.nope.value": 1})


def test_cross_reference_errors_are_reported() -> None:
    _, raw = load_raw_config(CONFIG_DIR)
    raw = apply_overrides(raw, {"dataset.noise_profile": "does_not_exist"})
    with pytest.raises(ConfigError, match="unknown noise profile"):
        build_config(raw)


def test_out_of_range_probability_fails() -> None:
    _, raw = load_raw_config(CONFIG_DIR)
    raw = apply_overrides(raw, {"noise.profiles": {**raw["noise"]["profiles"]}})
    raw["noise"]["profiles"]["low_noise"]["missing_title_probability"] = 1.5
    with pytest.raises(ConfigError, match="missing_title_probability"):
        build_config(raw)


def test_unknown_profile_lookup(config: OrgGraphConfig) -> None:
    with pytest.raises(ConfigError, match="unknown noise profile"):
        config.profile("nope")
