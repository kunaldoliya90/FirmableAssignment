# Company planning: totals, size segments and industry mix
from __future__ import annotations

from collections import Counter

import pytest
from orggraph_dataset.config import ConfigError, OrgGraphConfig
from orggraph_dataset.generators.company_generator import (
    assign_industries,
    assign_sizes,
    fit_counts_to_total,
    generate_company,
    generate_company_names,
    resolve_planned_total,
    segment_for_count,
)
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, plan_dataset
from orggraph_dataset.utils.random_utils import Rng

from tests.conftest import make_plan


def test_target_below_minimum_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="conflicts"):
        resolve_planned_total(500, 100, 40_000, 2.0, 20_000)


def test_target_above_maximum_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="exceeds"):
        resolve_planned_total(2, 100, 100_000, 2.0, 20_000)


def test_planned_total_respects_floor_and_diversity() -> None:
    assert resolve_planned_total(500, 100, 50_000, 2.0, 20_000) == 100_000
    assert resolve_planned_total(500, 100, 200_000, 2.0, 20_000) == 200_000


@pytest.mark.parametrize("target", [50_000, 200_000])
def test_sizes_hit_total_and_minimums(config: OrgGraphConfig, target: int) -> None:
    rng = Rng(3)
    industries = assign_industries(config, 500, rng.child("i"))
    planned = resolve_planned_total(500, 100, target, 2.0, 20_000)
    segments, counts = assign_sizes(config, industries, 100, planned, rng.child("s"))
    assert sum(counts) == planned
    assert min(counts) >= 100
    assert len(set(counts)) > 100, "company sizes must vary"
    assert all(segment_for_count(config, c) == s for c, s in zip(counts, segments, strict=True))
    assert len(set(segments)) == 5


def test_min_employees_override_is_respected(config: OrgGraphConfig) -> None:
    rng = Rng(5)
    industries = assign_industries(config, 40, rng)
    _, counts = assign_sizes(config, industries, 300, 40 * 300 * 2, rng)
    assert min(counts) >= 300


def test_fit_counts_exact() -> None:
    counts, residual = fit_counts_to_total([100, 200, 300], [100, 100, 100], [1000, 1000, 1000], 1234)
    assert residual == 0 and sum(counts) == 1234


def test_industries_and_names(config: OrgGraphConfig) -> None:
    industries = assign_industries(config, 500, Rng(1))
    assert len(Counter(industries)) == 19
    names = generate_company_names(config, industries, Rng(2))
    assert len({n.lower() for n in names}) == 500


def test_company_metadata(config: OrgGraphConfig) -> None:
    company, context = generate_company(make_plan(archetype="regional", employee_count=1200), config, Rng(9))
    assert company.employee_count == 1200
    assert len(company.operating_regions) >= 3
    assert context.headquarters in context.offices


def test_plan_assigns_archetypes_and_splits(config: OrgGraphConfig) -> None:
    plan = plan_dataset(
        config, GenerationSettings.from_config(config, companies=200, target_employees=60_000)
    )
    assert len({p.archetype for p in plan.companies}) >= 5
    splits = Counter(p.split for p in plan.companies)
    assert splits == {"train": 120, "validation": 30, "test": 30, "challenge": 20}
    for p in plan.companies:
        expected = "enterprise_complexity" if p.split == "challenge" else "medium_noise"
        assert p.noise_profile == expected
