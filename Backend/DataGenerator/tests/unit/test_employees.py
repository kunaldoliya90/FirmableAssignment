# Employee assignment and ground-truth reporting edges
from __future__ import annotations

from collections import Counter

from orggraph_dataset.schemas import CompanyRecords, EmploymentType


def test_employees_are_synthetic_and_unique(tech_company: CompanyRecords) -> None:
    ids = [e.employee_id for e in tech_company.employees]
    assert len(ids) == len(set(ids))
    for emp in tech_company.employees:
        assert emp.first_name and emp.last_name
        assert emp.full_name == f"{emp.first_name} {emp.last_name}"
        assert emp.employee_id.startswith("emp_00001_")
        assert emp.full_name not in emp.employee_id


def test_ids_do_not_follow_hierarchy_order(tech_company: CompanyRecords) -> None:
    ids = [e.employee_id for e in tech_company.employees]
    assert ids != sorted(ids)
    assert ids[0] != "emp_00001_000001"


def test_employment_types(tech_company: CompanyRecords) -> None:
    types = Counter(e.employment_type for e in tech_company.employees)
    assert types[EmploymentType.FULL_TIME] > types[EmploymentType.CONTRACTOR] > 0
    for emp in tech_company.employees:
        assert (emp.employment_type is EmploymentType.INTERN) == (emp.seniority_level.value == "intern")
        if emp.seniority_level.value in ("manager", "director", "vp", "c_level"):
            assert emp.employment_type is EmploymentType.FULL_TIME


def test_titles_come_from_positions(tech_company: CompanyRecords) -> None:
    positions = {p.position_id: p for p in tech_company.positions}
    for emp in tech_company.employees:
        pos = positions[emp.position_id]
        assert pos.canonical_title == emp.canonical_title
        assert pos.seniority_level == emp.seniority_level
        assert pos.job_family == emp.job_family


def test_observed_employees_cover_current_and_departed(tech_company: CompanyRecords) -> None:
    observed = {e.employee_id for e in tech_company.observed_employees}
    current = {e.employee_id for e in tech_company.employees}
    departed = {d.employee_id for d in tech_company.departed_employees}
    assert observed == current | departed
    assert not current & departed
