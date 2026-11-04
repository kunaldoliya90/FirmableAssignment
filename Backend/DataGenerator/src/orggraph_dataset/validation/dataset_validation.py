# Dataset validation: in-memory (before export) and on an exported directory (after reload)
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import METADATA_DIR
from orggraph_dataset.pipeline.loader import DatasetLayoutError, DatasetReader, RawCompanyChunk
from orggraph_dataset.schemas import (
    Company,
    CompanyRecords,
    DepartedEmployee,
    Department,
    Employee,
    EmployeeObservation,
    ObservationLabel,
    ObservedCompany,
    ObservedEmployee,
    Position,
    ReportingEdge,
    SecondaryEdge,
)
from orggraph_dataset.utils.jsonl import JsonlDecodeError, sha256_file
from orggraph_dataset.validation.company_validation import validate_company, validate_company_count
from orggraph_dataset.validation.employee_validation import validate_employees
from orggraph_dataset.validation.hierarchy_validation import validate_hierarchy
from orggraph_dataset.validation.leakage_validation import check_observed_record, validate_leakage
from orggraph_dataset.validation.observation_validation import validate_observations
from orggraph_dataset.validation.report import GlobalIdRegistry, ValidationContext, ValidationReport


def validate_records(
    records: CompanyRecords,
    ctx: ValidationContext,
    registry: GlobalIdRegistry,
    report: ValidationReport | None = None,
) -> ValidationReport:
    report = report or ValidationReport()
    validate_company(records, ctx, report, registry)
    validate_employees(records, report, registry)
    validate_hierarchy(records, report)
    validate_observations(records, ctx, report, registry)
    validate_leakage(records, report)
    return report


def _parse[M: BaseModel](
    model: type[M], rows: list[dict[str, Any]], what: str, cid: str, report: ValidationReport
) -> list[M] | None:
    parsed: list[M] = []
    failed = False
    for row in rows:
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            failed = True
            first = exc.errors()[0]
            location = ".".join(str(p) for p in first["loc"])
            report.error("schema.invalid_record", f"{what}: {location}: {first['msg']}", cid)
    return None if failed else parsed


def records_from_chunk(chunk: RawCompanyChunk, report: ValidationReport) -> CompanyRecords | None:
    cid = chunk.company_id
    gt, obs = chunk.ground_truth, chunk.observed
    if len(gt.get("companies", [])) != 1:
        report.error("schema.missing_company", "ground-truth company record missing or duplicated", cid)
        return None
    companies = _parse(Company, gt["companies"], "ground_truth/companies", cid, report)
    observed_company = _parse(ObservedCompany, obs["companies"], "observed/companies", cid, report)
    parts = {
        "departments": _parse(Department, gt["departments"], "departments", cid, report),
        "positions": _parse(Position, gt["positions"], "positions", cid, report),
        "employees": _parse(Employee, gt["canonical_roles"], "canonical_roles", cid, report),
        "reporting_edges": _parse(ReportingEdge, gt["reporting_edges"], "reporting_edges", cid, report),
        "secondary_edges": _parse(SecondaryEdge, gt["secondary_edges"], "secondary_edges", cid, report),
        "departed_employees": _parse(
            DepartedEmployee, gt["departed_employees"], "departed_employees", cid, report
        ),
        "observed_employees": _parse(ObservedEmployee, obs["employees"], "observed/employees", cid, report),
        "observations": _parse(EmployeeObservation, obs["observations"], "observations", cid, report),
        "observation_labels": _parse(
            ObservationLabel, gt["observation_labels"], "observation_labels", cid, report
        ),
    }
    if companies is None or observed_company is None or any(v is None for v in parts.values()):
        return None
    company = companies[0]
    if company.split.value != chunk.split:
        report.error(
            "split.wrong_directory",
            f"company is labelled {company.split.value} but stored in {chunk.split}",
            cid,
        )
    if company.to_observed() != observed_company[0]:
        report.error("company.observed_mismatch", "observed company differs from ground truth", cid)
    return CompanyRecords(company=company, **parts)  # type: ignore[arg-type]


def verify_checksums(reader: DatasetReader, report: ValidationReport) -> None:
    manifest = reader.manifest()
    if manifest is None:
        report.error("manifest.missing", f"{METADATA_DIR}/dataset_manifest.json not found")
        return
    for relative, expected in sorted(manifest.get("output_file_checksums", {}).items()):
        report.check("manifest.checksum")
        path = reader.root / relative
        if not path.exists():
            report.error("manifest.missing_file", f"{relative} listed in manifest but missing")
        elif sha256_file(path) != expected:
            report.error("manifest.checksum_mismatch", f"{relative} does not match its manifest checksum")


def validate_dataset_dir(
    dataset_dir: Path,
    config: OrgGraphConfig,
    min_companies: int | None = None,
    min_employees_per_company: int | None = None,
    min_total_employees: int | None = None,
    verify_manifest: bool = True,
) -> ValidationReport:
    report = ValidationReport()
    try:
        reader = DatasetReader(dataset_dir)
    except DatasetLayoutError as exc:
        report.error("layout.invalid", str(exc))
        return report

    ctx = ValidationContext.from_config(config, min_employees_per_company)
    registry = GlobalIdRegistry()
    split_of: dict[str, str] = {}
    counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()

    if verify_manifest:
        verify_checksums(reader, report)
    try:
        for split in reader.splits():
            for chunk in reader.iter_company_chunks(split):
                cid = chunk.company_id
                if cid in split_of:
                    report.error("split.company_in_multiple_splits", f"in {split_of[cid]} and {split}", cid)
                split_of[cid] = split
                split_counts[split] += 1
                for kind, rows in chunk.observed.items():
                    for row in rows:
                        check_observed_record(kind, row, report, cid)
                records = records_from_chunk(chunk, report)
                if records is None:
                    continue
                validate_records(records, ctx, registry, report)
                counts["companies"] += 1
                counts["employees"] += len(records.employees)
                counts["departed_employees"] += len(records.departed_employees)
                counts["observations"] += len(records.observations)
                counts["reporting_edges"] += sum(1 for e in records.reporting_edges if e.manager_employee_id)
                counts["secondary_edges"] += len(records.secondary_edges)
    except (DatasetLayoutError, JsonlDecodeError) as exc:
        report.error("layout.invalid", str(exc))

    validate_company_count(len(split_of), min_companies, report)
    if min_total_employees is not None and counts["employees"] < min_total_employees:
        report.error(
            "dataset.too_few_employees",
            f"{counts['employees']} employees < required {min_total_employees}",
        )

    split_manifest = reader.split_manifest()
    if split_manifest is not None:
        listed = {cid: split for split, ids in split_manifest.get("splits", {}).items() for cid in ids}
        if listed != split_of:
            report.error("split.manifest_mismatch", "split_manifest.json does not match the stored splits")
    manifest = reader.manifest()
    if manifest is not None:
        for key, field in (
            ("companies", "company_count"),
            ("employees", "employee_count"),
            ("observations", "observation_count"),
            ("reporting_edges", "reporting_edge_count"),
        ):
            if manifest.get(field) != counts[key]:
                report.error(
                    "manifest.count_mismatch",
                    f"manifest {field}={manifest.get(field)} but found {counts[key]}",
                )
    report.stats = {**dict(counts), "companies_per_split": dict(split_counts)}
    return report
