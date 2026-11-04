# Validators must accept generated data and loudly reject tampered data
from __future__ import annotations

import copy
from dataclasses import replace

from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.schemas import CompanyRecords, ReportingEdge
from orggraph_dataset.validation import GlobalIdRegistry, ValidationContext, validate_records
from orggraph_dataset.validation.hierarchy_validation import compute_depths, find_cycles
from orggraph_dataset.validation.leakage_validation import (
    check_observed_record,
    find_forbidden_keys,
    find_ground_truth_ids,
)
from orggraph_dataset.validation.report import ValidationReport


def _validate(config: OrgGraphConfig, records: CompanyRecords) -> ValidationReport:
    return validate_records(records, ValidationContext.from_config(config), GlobalIdRegistry())


def _with_edges(records: CompanyRecords, edges: list[ReportingEdge]) -> CompanyRecords:
    return replace(records, reporting_edges=edges)


def _edit_edge(records: CompanyRecords, index: int, **changes: object) -> CompanyRecords:
    edges = list(records.reporting_edges)
    edges[index] = edges[index].model_copy(update=changes)
    return _with_edges(records, edges)


def test_generated_company_is_valid(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    report = _validate(config, tech_company)
    assert report.ok, report.summary_lines()
    assert report.checks["observation"] == len(tech_company.observations)


def test_cycle_detection() -> None:
    assert find_cycles({"a": None, "b": "a", "c": "b"}) == []
    cycles = find_cycles({"a": "c", "b": "a", "c": "b", "d": None})
    assert len(cycles) == 1 and set(cycles[0]) == {"a", "b", "c"}
    assert compute_depths({"a": None, "b": "a", "c": "b"}) == {"a": 0, "b": 1, "c": 2}


def test_detects_cycle_in_reporting_edges(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    edges = list(tech_company.reporting_edges)
    root_index = next(i for i, e in enumerate(edges) if e.manager_employee_id is None)
    child = next(e for e in edges if e.manager_employee_id == edges[root_index].employee_id)
    edges[root_index] = ReportingEdge.model_construct(
        **{**edges[root_index].model_dump(), "manager_employee_id": child.employee_id}
    )
    report = _validate(config, _with_edges(tech_company, edges))
    assert report.issue_counts["hierarchy.cycle"] >= 1
    assert report.issue_counts["hierarchy.root_count"] == 0 or not report.ok


def test_detects_wrong_manager(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    index = next(i for i, e in enumerate(tech_company.reporting_edges) if e.hierarchy_depth >= 3)
    other = tech_company.reporting_edges[0].employee_id
    report = _validate(config, _edit_edge(tech_company, index, manager_employee_id=other))
    assert report.issue_counts["hierarchy.position_mismatch"] >= 1


def test_detects_cross_company_manager(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    index = next(i for i, e in enumerate(tech_company.reporting_edges) if e.manager_employee_id)
    report = _validate(config, _edit_edge(tech_company, index, manager_employee_id="emp_99999_000001"))
    assert report.issue_counts["hierarchy.unknown_manager"] == 1


def test_detects_duplicate_primary_manager(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    edges = [*tech_company.reporting_edges, tech_company.reporting_edges[5]]
    report = _validate(config, _with_edges(tech_company, edges))
    assert report.issue_counts["hierarchy.multiple_primary_managers"] == 1


def test_detects_missing_edge_and_bad_counts(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    report = _validate(config, _with_edges(tech_company, tech_company.reporting_edges[:-1]))
    assert report.issue_counts["hierarchy.missing_edge"] == 1
    company = tech_company.company.model_copy(update={"employee_count": 99})
    report = _validate(config, replace(tech_company, company=company))
    assert report.issue_counts["company.too_few_employees"] == 1
    assert report.issue_counts["company.employee_count_mismatch"] == 1


def test_detects_missing_field_misrepresentation(
    config: OrgGraphConfig, tech_company: CompanyRecords
) -> None:
    observations = list(tech_company.observations)
    observations[0] = observations[0].model_copy(update={"observed_title": None, "missing_fields": []})
    report = _validate(config, replace(tech_company, observations=observations))
    assert report.issue_counts["observation.missing_fields_mismatch"] == 1


def test_detects_duplicate_ids_across_companies(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    ctx = ValidationContext.from_config(config)
    registry = GlobalIdRegistry()
    assert validate_records(tech_company, ctx, registry).ok
    again = validate_records(tech_company, ctx, registry)
    assert again.issue_counts["company.duplicate_id"] == 1
    assert again.issue_counts["employee.duplicate_id"] > 0
    assert again.issue_counts["observation.duplicate_id"] > 0


def test_recursive_leakage_detection() -> None:
    record = {"employee_id": "e1", "extra": {"nested": [{"manager_employee_id": "e2"}]}}
    assert find_forbidden_keys(record) == ["extra.nested[0].manager_employee_id"]
    assert find_ground_truth_ids({"a": ["x", {"b": "pos_00001_000003"}]}) == ["a[1].b"]


def test_observed_record_leakage_is_reported() -> None:
    report = ValidationReport()
    leaked = {
        "employee_id": "e1",
        "company_id": "c1",
        "full_name": "A B",
        "first_name": "A",
        "last_name": "B",
        "employment_type": "full_time",
        "canonical_title": "CEO",
    }
    check_observed_record("employees", leaked, report, "c1")
    assert report.issue_counts["leakage.forbidden_field"] == 1
    assert report.issue_counts["leakage.unexpected_field"] == 1


def test_generated_observed_records_do_not_leak(tech_company: CompanyRecords) -> None:
    report = ValidationReport()
    for obs in tech_company.observations:
        check_observed_record("observations", obs.model_dump(mode="json"), report, None)
    for emp in tech_company.observed_employees:
        check_observed_record("employees", emp.model_dump(mode="json"), report, None)
    check_observed_record(
        "companies", tech_company.company.to_observed().model_dump(mode="json"), report, None
    )
    assert report.ok, report.summary_lines()


def test_validation_does_not_mutate(config: OrgGraphConfig, tech_company: CompanyRecords) -> None:
    before = copy.deepcopy([e.model_dump() for e in tech_company.reporting_edges])
    _validate(config, tech_company)
    assert before == [e.model_dump() for e in tech_company.reporting_edges]
