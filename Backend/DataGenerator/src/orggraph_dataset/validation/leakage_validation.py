# Leakage detection: observed records must contain only inference-allowed information
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from orggraph_dataset.constants import (
    FORBIDDEN_OBSERVED_FIELDS,
    GROUND_TRUTH_ID_PREFIXES,
    OBSERVED_ALLOWED_FIELDS,
)
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.validation.report import ValidationReport


def find_forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_OBSERVED_FIELDS:
                found.append(child_path)
            found += find_forbidden_keys(child, child_path)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found += find_forbidden_keys(child, f"{path}[{i}]")
    return found


def find_ground_truth_ids(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        if value.startswith(GROUND_TRUTH_ID_PREFIXES):
            found.append(path or "<value>")
    elif isinstance(value, dict):
        for key, child in value.items():
            found += find_ground_truth_ids(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found += find_ground_truth_ids(child, f"{path}[{i}]")
    return found


def check_observed_record(
    kind: str, record: dict[str, Any], report: ValidationReport, company_id: str | None
) -> None:
    report.check(f"leakage.{kind}")
    record_id = str(
        record.get("observation_id") or record.get("employee_id") or record.get("company_id") or ""
    )
    extra = set(record) - OBSERVED_ALLOWED_FIELDS[kind]
    if extra:
        report.error(
            "leakage.unexpected_field",
            f"{kind} record has non-whitelisted fields {sorted(extra)}",
            company_id,
            record_id,
        )
    for path in find_forbidden_keys(record):
        report.error(
            "leakage.forbidden_field",
            f"{kind} record exposes hidden field '{path}'",
            company_id,
            record_id,
        )
    for path in find_ground_truth_ids(record):
        report.error(
            "leakage.ground_truth_id",
            f"{kind} record contains a ground-truth identifier at '{path}'",
            company_id,
            record_id,
        )


def check_observed_records(
    kind: str, records: Iterable[dict[str, Any]], report: ValidationReport, company_id: str | None
) -> None:
    for record in records:
        check_observed_record(kind, record, report, company_id)


def validate_leakage(records: CompanyRecords, report: ValidationReport) -> None:
    cid = records.company.company_id
    check_observed_record("companies", records.company.to_observed().model_dump(mode="json"), report, cid)
    check_observed_records(
        "employees", (e.model_dump(mode="json") for e in records.observed_employees), report, cid
    )
    check_observed_records(
        "observations", (o.model_dump(mode="json") for o in records.observations), report, cid
    )

    current_ids = [e.employee_id for e in records.employees]
    observed_order = [e.employee_id for e in records.observed_employees]
    if len(current_ids) > 10 and observed_order[: len(current_ids)] == current_ids:
        report.error("leakage.hierarchy_order", "observed employees are in hierarchy order", cid)
