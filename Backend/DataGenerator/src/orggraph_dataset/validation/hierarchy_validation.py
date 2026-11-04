# Reporting-hierarchy constraints: references, single primary manager, acyclicity, depth
from __future__ import annotations

from collections.abc import Mapping

from orggraph_dataset.schemas import CompanyRecords, Employee, RelationshipType
from orggraph_dataset.validation.report import ValidationReport


def find_cycles(parent: Mapping[str, str | None]) -> list[list[str]]:
    state: dict[str, int] = {}
    cycles: list[list[str]] = []
    for start in parent:
        if state.get(start) == 2:
            continue
        path: list[str] = []
        node: str | None = start
        while node is not None and node in parent and state.get(node) != 2:
            if state.get(node) == 1:
                cycles.append(path[path.index(node) :])
                break
            state[node] = 1
            path.append(node)
            node = parent[node]
        for visited in path:
            state[visited] = 2
    return cycles


def compute_depths(parent: Mapping[str, str | None]) -> dict[str, int]:
    depths: dict[str, int] = {}
    for start in parent:
        chain: list[str] = []
        node: str | None = start
        while node is not None and node not in depths and node in parent:
            chain.append(node)
            node = parent[node]
            if len(chain) > len(parent):
                return depths
        if node is None:
            base = -1
        elif node in depths:
            base = depths[node]
        else:
            continue
        for offset, item in enumerate(reversed(chain), start=1):
            depths[item] = base + offset
    return depths


def validate_hierarchy(records: CompanyRecords, report: ValidationReport) -> None:
    cid = records.company.company_id
    employees = {e.employee_id: e for e in records.employees}
    report.check("hierarchy")
    parent, depth_claimed = _primary_edges(records, employees, report)
    _check_coverage_and_root(records, employees, parent, report)
    _check_cycles_and_depth(cid, parent, depth_claimed, report)
    _check_position_agreement(records, employees, parent, depth_claimed, report)
    _check_position_tree(records, report)
    _check_department_tree(records, report)
    _check_secondary_edges(records, employees, parent, report)


def _primary_edges(
    records: CompanyRecords, employees: Mapping[str, Employee], report: ValidationReport
) -> tuple[dict[str, str | None], dict[str, int]]:
    cid = records.company.company_id
    parent: dict[str, str | None] = {}
    depth_claimed: dict[str, int] = {}
    for edge in records.reporting_edges:
        report.check("reporting_edge")
        eid = edge.employee_id
        if edge.company_id != cid:
            report.error("hierarchy.wrong_company", "edge company_id mismatch", cid, eid)
        if eid not in employees:
            report.error("hierarchy.unknown_employee", "edge for an employee not in the company", cid, eid)
            continue
        if eid in parent:
            report.error(
                "hierarchy.multiple_primary_managers", "employee has more than one primary edge", cid, eid
            )
            continue
        manager = edge.manager_employee_id
        if manager is not None and manager not in employees:
            report.error(
                "hierarchy.unknown_manager", f"manager {manager} is not an employee of {cid}", cid, eid
            )
            manager = None
        if manager == eid:
            report.error("hierarchy.self_report", "employee reports to themselves", cid, eid)
        parent[eid] = manager
        depth_claimed[eid] = edge.hierarchy_depth
    return parent, depth_claimed


def _check_coverage_and_root(
    records: CompanyRecords,
    employees: Mapping[str, Employee],
    parent: Mapping[str, str | None],
    report: ValidationReport,
) -> None:
    cid = records.company.company_id
    missing = set(employees) - set(parent)
    if missing:
        report.error("hierarchy.missing_edge", f"{len(missing)} employees have no reporting edge", cid)
    roots = [e for e in records.reporting_edges if e.relationship_type is RelationshipType.ROOT]
    if len(roots) != 1:
        report.error("hierarchy.root_count", f"expected exactly 1 root, found {len(roots)}", cid)


def _check_cycles_and_depth(
    cid: str, parent: Mapping[str, str | None], depth_claimed: Mapping[str, int], report: ValidationReport
) -> None:
    cycles = find_cycles(parent)
    for cycle in cycles[:5]:
        report.error("hierarchy.cycle", f"reporting cycle: {' -> '.join(cycle)}", cid)
    if cycles:
        return
    depths = compute_depths(parent)
    wrong = [eid for eid, d in depth_claimed.items() if depths.get(eid) != d]
    if wrong:
        report.error(
            "hierarchy.depth_mismatch", f"{len(wrong)} edges have a wrong hierarchy_depth", cid, wrong[0]
        )


def _check_position_agreement(
    records: CompanyRecords,
    employees: Mapping[str, Employee],
    parent: Mapping[str, str | None],
    depth_claimed: Mapping[str, int],
    report: ValidationReport,
) -> None:
    holder = {e.position_id: e.employee_id for e in records.employees}
    positions = {p.position_id: p for p in records.positions}
    disagreements = 0
    for eid, manager in parent.items():
        position = positions.get(employees[eid].position_id)
        if position is None:
            continue
        expected = holder.get(position.parent_position_id) if position.parent_position_id else None
        if expected != manager:
            disagreements += 1
        if position.organizational_level != depth_claimed[eid]:
            disagreements += 1
    if disagreements:
        report.error(
            "hierarchy.position_mismatch",
            f"{disagreements} edges disagree with the position tree",
            records.company.company_id,
        )


def _check_position_tree(records: CompanyRecords, report: ValidationReport) -> None:
    cid = records.company.company_id
    position_parent = {p.position_id: p.parent_position_id for p in records.positions}
    for pid, ppid in position_parent.items():
        if ppid is not None and ppid not in position_parent:
            report.error(
                "hierarchy.unknown_parent_position", f"parent position {ppid} does not exist", cid, pid
            )
    if find_cycles(position_parent):
        report.error("hierarchy.position_cycle", "position tree contains a cycle", cid)


def _check_department_tree(records: CompanyRecords, report: ValidationReport) -> None:
    cid = records.company.company_id
    departments = {d.department_id: d for d in records.departments}
    for pos in records.positions:
        if pos.department_id not in departments:
            report.error(
                "hierarchy.unknown_department",
                f"department {pos.department_id} does not exist",
                cid,
                pos.position_id,
            )
    dept_parent = {d.department_id: d.parent_department_id for d in records.departments}
    for did, pdid in dept_parent.items():
        if pdid is not None and pdid not in dept_parent:
            report.error("hierarchy.unknown_parent_department", f"parent department {pdid} missing", cid, did)
    if find_cycles(dept_parent):
        report.error("hierarchy.department_cycle", "department tree contains a cycle", cid)


def _check_secondary_edges(
    records: CompanyRecords,
    employees: Mapping[str, Employee],
    parent: Mapping[str, str | None],
    report: ValidationReport,
) -> None:
    cid = records.company.company_id
    for sec in records.secondary_edges:
        report.check("secondary_edge")
        if sec.employee_id not in employees or sec.manager_employee_id not in employees:
            report.error(
                "hierarchy.secondary_unknown_employee",
                "secondary edge references unknown employee",
                cid,
                sec.employee_id,
            )
        elif parent.get(sec.employee_id) == sec.manager_employee_id:
            report.error(
                "hierarchy.secondary_equals_primary",
                "secondary manager equals primary manager",
                cid,
                sec.employee_id,
            )
