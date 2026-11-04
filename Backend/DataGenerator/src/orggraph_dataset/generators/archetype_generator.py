# Organizational archetype selection and segment naming
from __future__ import annotations

from orggraph_dataset.config import ArchetypeConfig, OrgGraphConfig, SegmentLayerConfig
from orggraph_dataset.generators.company_generator import CompanyContext
from orggraph_dataset.utils.random_utils import Rng


def eligible_archetypes(config: OrgGraphConfig, employee_count: int) -> list[str]:
    return [
        key
        for key, arch in config.archetypes.archetypes.items()
        if arch.min_employees <= employee_count
        and (arch.max_employees is None or employee_count <= arch.max_employees)
    ]


def select_archetype(
    config: OrgGraphConfig, industry: str, size_segment: str, employee_count: int, rng: Rng
) -> str:
    industry_weights = config.industries.industries[industry].archetype_weights
    candidates = eligible_archetypes(config, employee_count)
    weights = [
        industry_weights.get(key, 0.0) * config.archetypes.archetypes[key].size_weights.get(size_segment, 0.0)
        for key in candidates
    ]
    if not candidates or sum(weights) <= 0:
        return "functional"
    return rng.weighted_choice(candidates, weights)


def archetype_spec(config: OrgGraphConfig, key: str) -> ArchetypeConfig:
    return config.archetypes.archetypes[key]


def segment_names(
    config: OrgGraphConfig,
    layer: SegmentLayerConfig,
    industry: str,
    context: CompanyContext,
    count: int,
    parent_name: str | None,
    rng: Rng,
) -> list[tuple[str, str | None]]:
    industry_cfg = config.industries.industries[industry]
    if layer.kind == "region":
        keys = list(context.region_keys[:count])
        return [(config.locations.regions[k].name, k) for k in keys]
    if layer.kind == "business_unit":
        pool = list(industry_cfg.business_units)
    elif layer.kind == "product_line":
        pool = list(industry_cfg.product_lines)
    else:
        base = parent_name or "Core"
        pool = [p.format(parent=base) for p in config.archetypes.division_name_patterns]
    rng.shuffle(pool)
    names = pool[:count]
    while len(names) < count:
        names.append(f"{rng.choice(pool)} {len(names) + 1}")
    return [(name, None) for name in names]


def segment_count(layer: SegmentLayerConfig, available_headcount: int, max_segments: int, rng: Rng) -> int:
    low, high = layer.count
    wanted = rng.randint(low, high)
    return max(0, min(wanted, max_segments, available_headcount // layer.min_headcount))
