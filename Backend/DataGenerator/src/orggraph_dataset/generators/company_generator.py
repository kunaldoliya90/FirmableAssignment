# Company planning: totals, size segments, industries, names and company metadata
from __future__ import annotations

import math
from dataclasses import dataclass

from orggraph_dataset.config import CityConfig, ConfigError, OrgGraphConfig
from orggraph_dataset.constants import SIZE_SEGMENTS
from orggraph_dataset.schemas import Company, OrgArchetype, SizeSegment, Split
from orggraph_dataset.utils.ids import company_id
from orggraph_dataset.utils.random_utils import Rng, largest_remainder


@dataclass(frozen=True)
class CompanyPlan:
    index: int
    company_id: str
    company_name: str
    industry: str
    size_segment: str
    employee_count: int
    archetype: str
    split: str
    noise_profile: str
    generation_seed: int


@dataclass(frozen=True)
class CompanyContext:
    headquarters: CityConfig
    region_keys: tuple[str, ...]
    offices: tuple[CityConfig, ...]


def resolve_planned_total(
    companies: int,
    min_employees: int,
    target_employees: int,
    diversity_multiplier: float,
    max_per_company: int,
) -> int:
    if companies < 1:
        raise ConfigError("--companies must be at least 1")
    if min_employees < 1:
        raise ConfigError("--min-employees-per-company must be at least 1")
    if min_employees > max_per_company:
        raise ConfigError(
            f"--min-employees-per-company {min_employees} exceeds the largest company size "
            f"allowed by company_sizes.yaml ({max_per_company})"
        )
    floor = companies * min_employees
    if target_employees < floor:
        raise ConfigError(
            f"--target-employees {target_employees:,} conflicts with --companies {companies} x "
            f"--min-employees-per-company {min_employees} = {floor:,}; raise the target or lower "
            "the minimum / company count"
        )
    ceiling = companies * max_per_company
    if target_employees > ceiling:
        raise ConfigError(
            f"--target-employees {target_employees:,} exceeds {companies} companies x the largest "
            f"company size {max_per_company:,} = {ceiling:,}; add companies or raise "
            "company_sizes.enterprise.max"
        )
    planned = max(target_employees, math.ceil(floor * diversity_multiplier))
    return min(planned, ceiling)


def effective_segment_bounds(config: OrgGraphConfig, min_employees: int) -> dict[str, tuple[int, int]]:
    bounds: dict[str, tuple[int, int]] = {}
    for key, seg in config.company_sizes.segments.items():
        low = max(seg.min, min_employees)
        if low <= seg.max:
            bounds[key] = (low, seg.max)
    return bounds


def skewed_size(low: int, high: int, skew: float, u: float) -> int:
    return round(low * math.pow(high / low, math.pow(u, skew)))


def typical_size(low: int, high: int, skew: float) -> float:
    points = [(i + 0.5) / 64 for i in range(64)]
    return sum(low * math.pow(high / low, math.pow(u, skew)) for u in points) / len(points)


def fit_segment_mix(
    base_counts: dict[str, int],
    bounds: dict[str, tuple[int, int]],
    planned: int,
    keep_min: int,
    skew: float = 1.0,
) -> dict[str, int]:
    order = [s for s in SIZE_SEGMENTS if s in bounds]
    counts = {s: base_counts.get(s, 0) for s in order}
    typical = {s: typical_size(bounds[s][0], bounds[s][1], skew) for s in order}

    def expected() -> float:
        return sum(counts[s] * typical[s] for s in order)

    def shift(down: bool, floor: int) -> bool:
        moved = False
        indices = range(len(order) - 1, 0, -1) if down else range(len(order) - 1)
        for i in indices:
            src, dst = order[i], order[i - 1 if down else i + 1]
            if counts[src] > floor:
                counts[src] -= 1
                counts[dst] += 1
                moved = True
                if (expected() <= planned) if down else (expected() >= planned):
                    return True
        return moved

    while expected() > planned:
        if not shift(True, keep_min) and not shift(True, 0):
            break
    while expected() < planned:
        if not shift(False, keep_min) and not shift(False, 0):
            break
    return counts


def fit_counts_to_total(
    counts: list[int], lows: list[int], highs: list[int], total: int
) -> tuple[list[int], int]:
    values = [float(c) for c in counts]
    for _ in range(200):
        diff = total - sum(values)
        if abs(diff) < 0.5:
            break
        room = (
            [h - v for v, h in zip(values, highs, strict=True)]
            if diff > 0
            else [v - lo for v, lo in zip(values, lows, strict=True)]
        )
        weights = [v if r > 1e-9 else 0.0 for v, r in zip(values, room, strict=True)]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            break
        for i, weight in enumerate(weights):
            if weight:
                step = diff * weight / weight_sum
                values[i] += min(step, room[i]) if diff > 0 else max(step, -room[i])
    ints = [min(max(round(v), lo), hi) for v, lo, hi in zip(values, lows, highs, strict=True)]
    residual = total - sum(ints)
    order = sorted(range(len(ints)), key=lambda i: (-ints[i], i))
    while residual:
        progressed = False
        for i in order:
            if residual > 0 and ints[i] < highs[i]:
                ints[i] += 1
                residual -= 1
                progressed = True
            elif residual < 0 and ints[i] > lows[i]:
                ints[i] -= 1
                residual += 1
                progressed = True
            if not residual:
                break
        if not progressed:
            break
    return ints, residual


def segment_for_count(config: OrgGraphConfig, count: int) -> str:
    for key, seg in config.company_sizes.segments.items():
        if seg.min <= count <= seg.max:
            return key
    return (
        SIZE_SEGMENTS[0] if count < config.company_sizes.segments[SIZE_SEGMENTS[0]].min else SIZE_SEGMENTS[-1]
    )


def assign_industries(config: OrgGraphConfig, companies: int, rng: Rng) -> list[str]:
    keys = list(config.industries.industries)
    counts = largest_remainder(companies, [config.industries.industries[k].weight for k in keys])
    industries = [key for key, n in zip(keys, counts, strict=True) for _ in range(n)]
    rng.shuffle(industries)
    return industries


def assign_sizes(
    config: OrgGraphConfig,
    industries: list[str],
    min_employees: int,
    planned_total: int,
    rng: Rng,
) -> tuple[list[str], list[int]]:
    n = len(industries)
    bounds = effective_segment_bounds(config, min_employees)
    if not bounds:
        raise ConfigError("no company-size segment can satisfy --min-employees-per-company")
    defaults = config.company_sizes.segments
    order = [s for s in SIZE_SEGMENTS if s in bounds]
    base = dict(zip(order, largest_remainder(n, [defaults[s].default_count for s in order]), strict=True))
    skew = config.company_sizes.within_segment_skew
    mix = fit_segment_mix(base, bounds, planned_total, config.company_sizes.keep_min_per_segment, skew)

    segments: list[str | None] = [None] * n
    unassigned = list(range(n))
    for seg in reversed(order[1:]):
        weights = [config.industries.industries[industries[i]].size_weights.get(seg, 1.0) for i in unassigned]
        chosen = set(rng.weighted_sample_without_replacement(unassigned, weights, mix[seg]))
        for i in chosen:
            segments[i] = seg
        unassigned = [i for i in unassigned if i not in chosen]
    for i in unassigned:
        segments[i] = order[0]
    resolved = [s or order[0] for s in segments]

    counts = [skewed_size(bounds[s][0], bounds[s][1], skew, rng.random()) for s in resolved]
    lows = [bounds[s][0] for s in resolved]
    highs = [bounds[s][1] for s in resolved]
    counts, residual = fit_counts_to_total(counts, lows, highs, planned_total)
    if residual:
        global_low = min(b[0] for b in bounds.values())
        global_high = max(b[1] for b in bounds.values())
        counts, residual = fit_counts_to_total(counts, [global_low] * n, [global_high] * n, planned_total)
    if residual:
        raise ConfigError(f"could not distribute {planned_total:,} employees across {n} companies")
    return [segment_for_count(config, c) for c in counts], counts


def generate_company_names(config: OrgGraphConfig, industries: list[str], rng: Rng) -> list[str]:
    naming = config.industries.naming
    used: set[str] = set()
    names: list[str] = []
    for industry in industries:
        suffixes = config.industries.industries[industry].name_suffixes
        name = ""
        for attempt in range(60):
            first, second = rng.choice(naming.first_parts), rng.choice(naming.second_parts)
            stem = f"{first}{second.lower()}" if rng.bernoulli(0.5) else f"{first} {second}"
            name = f"{stem} {rng.choice(suffixes)}"
            if attempt >= 40:
                name = f"{name} {attempt - 38}"
            if name.lower() not in used:
                break
        used.add(name.lower())
        names.append(name)
    return names


def generate_company(plan: CompanyPlan, config: OrgGraphConfig, rng: Rng) -> tuple[Company, CompanyContext]:
    industry = config.industries.industries[plan.industry]
    locations = config.locations
    region_weights = {r: industry.region_weights.get(r, 0.0) for r in locations.regions}
    hq_region = rng.weighted_key(region_weights)
    hq_city = rng.choice([c for c in locations.cities if c.region == hq_region])

    low, high = locations.operating_regions_by_size[plan.size_segment]
    extra = rng.randint(low, high)
    if plan.archetype == OrgArchetype.REGIONAL:
        extra = max(extra, 2)
    others = [r for r in locations.regions if r != hq_region]
    extra_regions = rng.weighted_sample_without_replacement(
        others, [max(region_weights[r], 0.1) for r in others], min(extra, len(others))
    )
    region_keys = (hq_region, *extra_regions)

    offices: list[CityConfig] = [hq_city]
    office_low, office_high = locations.offices_per_region_by_size[plan.size_segment]
    for region in region_keys:
        pool = [c for c in locations.cities if c.region == region and c not in offices]
        wanted = rng.randint(office_low, office_high) - (1 if region == hq_region else 0)
        offices += rng.sample(pool, min(max(wanted, 0 if region == hq_region else 1), len(pool)))

    company = Company(
        company_id=plan.company_id,
        company_name=plan.company_name,
        industry=industry.name,
        employee_count=plan.employee_count,
        company_size_segment=SizeSegment(plan.size_segment),
        headquarters=f"{hq_city.name}, {hq_city.country}",
        operating_regions=[locations.regions[r].name for r in region_keys],
        org_archetype=OrgArchetype(plan.archetype),
        generation_seed=plan.generation_seed,
        noise_profile=plan.noise_profile,
        split=Split(plan.split),
    )
    return company, CompanyContext(headquarters=hq_city, region_keys=region_keys, offices=tuple(offices))


def make_company_id(index: int) -> str:
    return company_id(index)
