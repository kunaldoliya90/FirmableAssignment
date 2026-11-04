# Employee-level constraints for canonical, departed and observed employee records
from __future__ import annotations

from orggraph_dataset.schemas import CompanyRecords, EmploymentType, SeniorityLevel
from orggraph_dataset.validation.report import GlobalIdRegistry, ValidationReport


def validate_employees(records: CompanyRecords, report: ValidationReport, registry: GlobalIdRegistry) -> None:
    cid = records.company.company_id
    positions = {p.position_id: p for p in records.positions}
    held: set[str] = set()
    seen: set[str] = set()

    for emp in records.employees:
        report.check("employee")
        eid = emp.employee_id
        if eid in seen or eid in registry.employee_ids:
            report.error("employee.duplicate_id", "employee_id is not unique", cid, eid)
        seen.add(eid)
        if emp.company_id != cid:
            report.error("employee.wrong_company", f"company_id {emp.company_id} != {cid}", cid, eid)
        if not emp.first_name.strip() or not emp.last_name.strip() or emp.full_name in (eid, cid):
            report.error(
                "employee.invalid_identity",
                "synthetic identity fields are empty or reuse IDs",
                cid,
                eid,
            )
        position = positions.get(emp.position_id)
        if position is None:
            report.error("employee.unknown_position", f"position {emp.position_id} does not exist", cid, eid)
            continue
        if emp.position_id in held:
            report.error("employee.shared_position", f"position {emp.position_id} has two holders", cid, eid)
        held.add(emp.position_id)
        if position.canonical_title != emp.canonical_title or position.seniority_level != emp.seniority_level:
            report.error(
                "employee.position_mismatch",
                "title/seniority differ from the held position",
                cid,
                eid,
            )
        is_intern_level = emp.seniority_level is SeniorityLevel.INTERN
        if is_intern_level != (emp.employment_type is EmploymentType.INTERN):
            report.error(
                "employee.intern_mismatch",
                "intern seniority and intern employment type disagree",
                cid,
                eid,
            )

    unfilled = set(positions) - held
    if unfilled:
        report.error("employee.unfilled_positions", f"{len(unfilled)} positions have no employee", cid)

    departed_ids: set[str] = set()
    for person in records.departed_employees:
        report.check("departed_employee")
        if (
            person.employee_id in seen
            or person.employee_id in departed_ids
            or person.employee_id in registry.employee_ids
        ):
            report.error(
                "employee.duplicate_id",
                "departed employee_id is not unique",
                cid,
                person.employee_id,
            )
        departed_ids.add(person.employee_id)

    expected = seen | departed_ids
    observed_ids = [e.employee_id for e in records.observed_employees]
    if len(observed_ids) != len(set(observed_ids)):
        report.error("employee.duplicate_observed", "observed employees list contains duplicates", cid)
    if set(observed_ids) != expected:
        report.error(
            "employee.observed_mismatch",
            f"observed employees ({len(set(observed_ids))}) != canonical + departed ({len(expected)})",
            cid,
        )
    canonical_names = {e.employee_id: e.full_name for e in records.employees}
    canonical_names.update({d.employee_id: d.full_name for d in records.departed_employees})
    for obs_emp in records.observed_employees:
        if obs_emp.company_id != cid:
            report.error(
                "employee.wrong_company",
                "observed employee in wrong company",
                cid,
                obs_emp.employee_id,
            )
        if canonical_names.get(obs_emp.employee_id) not in (None, obs_emp.full_name):
            report.error(
                "employee.name_mismatch",
                "observed name differs from canonical",
                cid,
                obs_emp.employee_id,
            )
    registry.employee_ids.update(expected)
