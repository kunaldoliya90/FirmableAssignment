# Dataset manifest, split manifest, generation config snapshot and summary
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orggraph_dataset import __version__
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import GROUND_TRUTH_DIR, OBSERVED_DIR, SCHEMA_VERSION, SPLITS
from orggraph_dataset.schemas import CompanyRecords, DatasetManifest, SplitManifest
from orggraph_dataset.utils.jsonl import sha256_file


@dataclass
class DatasetTally:
    companies: int = 0
    employees: int = 0
    departed: int = 0
    observations: int = 0
    reporting_edges: int = 0
    roots: int = 0
    secondary_edges: int = 0
    industries: Counter[str] = field(default_factory=Counter)
    sizes: Counter[str] = field(default_factory=Counter)
    archetypes: Counter[str] = field(default_factory=Counter)
    noise_profiles: Counter[str] = field(default_factory=Counter)
    split_companies: Counter[str] = field(default_factory=Counter)
    split_employees: Counter[str] = field(default_factory=Counter)
    split_observations: Counter[str] = field(default_factory=Counter)
    split_ids: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    seniority: Counter[str] = field(default_factory=Counter)
    noise_operations: Counter[str] = field(default_factory=Counter)
    missing_fields: Counter[str] = field(default_factory=Counter)
    sources: Counter[str] = field(default_factory=Counter)
    depth_by_archetype: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    depth_by_size: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    max_span: int = 0
    span_sum: float = 0.0
    manager_count: int = 0

    def add(self, records: CompanyRecords) -> None:
        company = records.company
        split = company.split.value
        self.companies += 1
        self.employees += len(records.employees)
        self.departed += len(records.departed_employees)
        self.observations += len(records.observations)
        self.reporting_edges += sum(1 for e in records.reporting_edges if e.manager_employee_id)
        self.roots += sum(1 for e in records.reporting_edges if e.manager_employee_id is None)
        self.secondary_edges += len(records.secondary_edges)
        self.industries[company.industry] += 1
        self.sizes[company.company_size_segment.value] += 1
        self.archetypes[company.org_archetype.value] += 1
        self.noise_profiles[company.noise_profile] += 1
        self.split_companies[split] += 1
        self.split_employees[split] += len(records.employees)
        self.split_observations[split] += len(records.observations)
        self.split_ids[split].append(company.company_id)
        stats = records.stats
        self.seniority.update(stats.get("seniority_counts", {}))
        self.noise_operations.update(stats.get("noise_operation_counts", {}))
        for obs in records.observations:
            self.missing_fields.update(obs.missing_fields)
        for label in records.observation_labels:
            self.sources[label.true_source.value] += 1
        self.depth_by_archetype[company.org_archetype.value].append(stats.get("max_depth", 0))
        self.depth_by_size[company.company_size_segment.value].append(stats.get("max_depth", 0))
        self.max_span = max(self.max_span, stats.get("max_span", 0))
        managers = stats.get("manager_count", 0)
        self.manager_count += managers
        self.span_sum += stats.get("mean_span", 0.0) * managers


def file_checksums(output_dir: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for tree in (OBSERVED_DIR, GROUND_TRUTH_DIR):
        for path in sorted((output_dir / tree).rglob("*.jsonl")):
            checksums[path.relative_to(output_dir).as_posix()] = sha256_file(path)
    return checksums


def _sorted(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def build_manifest(
    config: OrgGraphConfig,
    tally: DatasetTally,
    seed: int,
    requested_target: int,
    planned_total: int,
    noise_profile: str,
    challenge_profile: str,
    checksums: dict[str, str],
    record_counts: dict[str, int],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_version=config.dataset.dataset_version,
        schema_version=SCHEMA_VERSION,
        generator_version=__version__,
        generation_timestamp=datetime.now(UTC).replace(microsecond=0).isoformat(),
        random_seed=seed,
        requested_target_employees=requested_target,
        planned_employee_total=planned_total,
        company_count=tally.companies,
        employee_count=tally.employees,
        departed_employee_count=tally.departed,
        observation_count=tally.observations,
        reporting_edge_count=tally.reporting_edges,
        root_count=tally.roots,
        secondary_edge_count=tally.secondary_edges,
        industry_distribution=_sorted(tally.industries),
        company_size_distribution=_sorted(tally.sizes),
        archetype_distribution=_sorted(tally.archetypes),
        noise_profile={
            "base_profile": noise_profile,
            "challenge_profile": challenge_profile,
            "profiles": {
                name: config.profile(name).model_dump() for name in sorted({noise_profile, challenge_profile})
            },
        },
        noise_profile_distribution=_sorted(tally.noise_profiles),
        split_distribution={
            split: {
                "companies": tally.split_companies[split],
                "employees": tally.split_employees[split],
                "observations": tally.split_observations[split],
            }
            for split in SPLITS
        },
        output_file_checksums=checksums,
        record_counts=dict(sorted(record_counts.items())),
    )


def build_split_manifest(config: OrgGraphConfig, tally: DatasetTally, seed: int) -> SplitManifest:
    return SplitManifest(
        seed=seed,
        fractions=dict(config.dataset.splits.fractions),
        holdout_industries=list(config.dataset.splits.holdout_industries),
        splits={split: sorted(tally.split_ids.get(split, [])) for split in SPLITS},
        company_counts={split: tally.split_companies[split] for split in SPLITS},
        employee_counts={split: tally.split_employees[split] for split in SPLITS},
    )


def build_summary(tally: DatasetTally, elapsed_seconds: float) -> dict[str, Any]:
    def depth_stats(groups: dict[str, list[int]]) -> dict[str, dict[str, float]]:
        return {
            key: {
                "companies": len(v),
                "min": min(v),
                "mean": round(sum(v) / len(v), 2),
                "max": max(v),
            }
            for key, v in sorted(groups.items())
            if v
        }

    return {
        "elapsed_seconds": round(elapsed_seconds, 1),
        "companies": tally.companies,
        "employees": tally.employees,
        "departed_employees": tally.departed,
        "observations": tally.observations,
        "observations_per_employee": round(tally.observations / max(tally.employees, 1), 3),
        "reporting_edges": tally.reporting_edges,
        "secondary_edges": tally.secondary_edges,
        "seniority_distribution": _sorted(tally.seniority),
        "hierarchy_depth_by_archetype": depth_stats(tally.depth_by_archetype),
        "hierarchy_depth_by_size": depth_stats(tally.depth_by_size),
        "span_of_control": {
            "managers": tally.manager_count,
            "mean": round(tally.span_sum / max(tally.manager_count, 1), 2),
            "max": tally.max_span,
        },
        "observations_by_source": _sorted(tally.sources),
        "missing_field_counts": _sorted(tally.missing_fields),
        "noise_operation_counts": _sorted(tally.noise_operations),
    }
