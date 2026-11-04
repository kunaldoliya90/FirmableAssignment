# End-to-end generation pipeline
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import (
    GENERATION_CONFIG_FILE,
    GENERATION_SUMMARY_FILE,
    MANIFEST_FILE,
    METADATA_DIR,
    SPLIT_MANIFEST_FILE,
    VALIDATION_REPORT_FILE,
)
from orggraph_dataset.generators.archetype_generator import select_archetype
from orggraph_dataset.generators.company_generator import (
    CompanyPlan,
    assign_industries,
    assign_sizes,
    generate_company_names,
    make_company_id,
    resolve_planned_total,
)
from orggraph_dataset.pipeline.dataset_builder import CompanyBuilder
from orggraph_dataset.pipeline.exporter import DatasetExporter, prepare_output_dir
from orggraph_dataset.pipeline.manifest import (
    DatasetTally,
    build_manifest,
    build_split_manifest,
    build_summary,
    file_checksums,
)
from orggraph_dataset.pipeline.splitting import SplitCandidate, assign_splits
from orggraph_dataset.schemas import DatasetManifest
from orggraph_dataset.utils.jsonl import write_json
from orggraph_dataset.utils.logging import get_logger
from orggraph_dataset.utils.random_utils import Rng, derive_seed
from orggraph_dataset.validation import (
    GlobalIdRegistry,
    ValidationContext,
    ValidationReport,
    validate_dataset_dir,
    validate_records,
)

log = get_logger("pipeline")


class GenerationValidationError(RuntimeError):
    def __init__(self, report: ValidationReport, where: str) -> None:
        lines = "\n  ".join(report.summary_lines())
        super().__init__(f"validation failed {where} ({report.error_count} issues):\n  {lines}")
        self.report = report


@dataclass(frozen=True)
class GenerationSettings:
    companies: int
    min_employees_per_company: int
    target_employees: int
    seed: int
    noise_profile: str
    challenge_noise_profile: str
    output_dir: Path
    batch_size: int
    overwrite: bool = False
    validate_after_export: bool = True

    @classmethod
    def from_config(cls, config: OrgGraphConfig, **overrides: Any) -> GenerationSettings:
        ds = config.dataset
        values: dict[str, Any] = {
            "companies": ds.companies,
            "min_employees_per_company": ds.min_employees_per_company,
            "target_employees": ds.target_employees,
            "seed": ds.seed,
            "noise_profile": ds.noise_profile,
            "challenge_noise_profile": ds.challenge_noise_profile,
            "output_dir": Path(ds.output_dir),
            "batch_size": ds.batch_size,
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        values["output_dir"] = Path(values["output_dir"])
        return cls(**values)


@dataclass
class DatasetPlan:
    planned_total: int
    companies: list[CompanyPlan]


@dataclass
class GenerationResult:
    output_dir: Path
    manifest: DatasetManifest
    summary: dict[str, Any]
    validation: ValidationReport | None
    plan: DatasetPlan = field(repr=False)


def plan_dataset(config: OrgGraphConfig, settings: GenerationSettings) -> DatasetPlan:
    config.profile(settings.noise_profile)
    config.profile(settings.challenge_noise_profile)
    max_size = config.company_sizes.segments["enterprise"].max
    planned_total = resolve_planned_total(
        settings.companies,
        settings.min_employees_per_company,
        settings.target_employees,
        config.dataset.size_diversity_multiplier,
        max_size,
    )
    rng = Rng(derive_seed(settings.seed, "plan"))
    industries = assign_industries(config, settings.companies, rng.child("industries"))
    segments, counts = assign_sizes(
        config, industries, settings.min_employees_per_company, planned_total, rng.child("sizes")
    )
    names = generate_company_names(config, industries, rng.child("names"))
    archetype_rng = rng.child("archetypes")
    archetypes = [
        select_archetype(config, ind, seg, n, archetype_rng)
        for ind, seg, n in zip(industries, segments, counts, strict=True)
    ]
    splits = assign_splits(
        [SplitCandidate(i, s, a) for i, s, a in zip(industries, segments, archetypes, strict=True)],
        config.dataset.splits,
        rng.child("splits"),
    )
    plans = [
        CompanyPlan(
            index=i + 1,
            company_id=make_company_id(i + 1),
            company_name=names[i],
            industry=industries[i],
            size_segment=segments[i],
            employee_count=counts[i],
            archetype=archetypes[i],
            split=splits[i],
            noise_profile=settings.challenge_noise_profile
            if splits[i] == "challenge"
            else settings.noise_profile,
            generation_seed=derive_seed(settings.seed, "company", i + 1),
        )
        for i in range(settings.companies)
    ]
    return DatasetPlan(planned_total=planned_total, companies=plans)


def run_generation(
    config: OrgGraphConfig,
    settings: GenerationSettings,
    raw_config: dict[str, Any] | None = None,
    progress: Callable[[int, int, int], None] | None = None,
) -> GenerationResult:
    started = time.perf_counter()
    plan = plan_dataset(config, settings)
    log.info(
        "planned %d companies, %s employees (requested target %s)",
        len(plan.companies),
        f"{plan.planned_total:,}",
        f"{settings.target_employees:,}",
    )
    output_dir = settings.output_dir
    prepare_output_dir(output_dir, settings.overwrite)

    builder = CompanyBuilder(config)
    ctx = ValidationContext.from_config(config, settings.min_employees_per_company)
    registry = GlobalIdRegistry()
    tally = DatasetTally()
    exporter = DatasetExporter(output_dir)
    try:
        total = len(plan.companies)
        for start in range(0, total, settings.batch_size):
            batch = plan.companies[start : start + settings.batch_size]
            for company_plan in batch:
                records = builder.build(company_plan)
                report = validate_records(records, ctx, registry)
                if not report.ok:
                    raise GenerationValidationError(report, f"for {company_plan.company_id} before export")
                exporter.write(records)
                tally.add(records)
            exporter.flush()
            done = min(start + settings.batch_size, total)
            log.info("generated %d/%d companies (%s employees)", done, total, f"{tally.employees:,}")
            if progress:
                progress(done, total, tally.employees)
    finally:
        record_counts = exporter.close()

    metadata = output_dir / METADATA_DIR
    split_manifest = build_split_manifest(config, tally, settings.seed)
    write_json(metadata / SPLIT_MANIFEST_FILE, split_manifest.model_dump(mode="json"))
    write_json(
        metadata / GENERATION_CONFIG_FILE,
        {
            "settings": {
                "companies": settings.companies,
                "min_employees_per_company": settings.min_employees_per_company,
                "target_employees": settings.target_employees,
                "planned_employee_total": plan.planned_total,
                "seed": settings.seed,
                "noise_profile": settings.noise_profile,
                "challenge_noise_profile": settings.challenge_noise_profile,
                "batch_size": settings.batch_size,
            },
            "config": raw_config if raw_config is not None else config.model_dump(mode="json"),
        },
    )
    manifest = build_manifest(
        config,
        tally,
        settings.seed,
        settings.target_employees,
        plan.planned_total,
        settings.noise_profile,
        settings.challenge_noise_profile,
        file_checksums(output_dir),
        record_counts,
    )
    write_json(metadata / MANIFEST_FILE, manifest.model_dump(mode="json"))
    summary = build_summary(tally, time.perf_counter() - started)
    write_json(metadata / GENERATION_SUMMARY_FILE, summary)

    validation: ValidationReport | None = None
    if settings.validate_after_export:
        log.info("re-validating exported dataset from disk")
        validation = validate_dataset_dir(
            output_dir,
            config,
            min_companies=settings.companies,
            min_employees_per_company=settings.min_employees_per_company,
            min_total_employees=settings.target_employees,
        )
        write_json(metadata / VALIDATION_REPORT_FILE, validation.to_dict())
        if not validation.ok:
            raise GenerationValidationError(validation, "after export")
    return GenerationResult(output_dir, manifest, summary, validation, plan)
