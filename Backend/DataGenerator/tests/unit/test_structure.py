# Departments, archetypes, hierarchy and positions
from __future__ import annotations

from collections import Counter

import pytest
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import SENIORITY_RANK
from orggraph_dataset.generators.archetype_generator import eligible_archetypes, select_archetype
from orggraph_dataset.pipeline.dataset_builder import CompanyBuilder
from orggraph_dataset.schemas import CompanyRecords, DepartmentType
from orggraph_dataset.utils.random_utils import Rng
from orggraph_dataset.validation.hierarchy_validation import find_cycles

from tests.conftest import make_plan


def _children(records: CompanyRecords) -> Counter[str]:
    return Counter(e.manager_employee_id for e in records.reporting_edges if e.manager_employee_id)


def test_archetype_eligibility_by_size(config: OrgGraphConfig) -> None:
    assert "enterprise" not in eligible_archetypes(config, 300)
    assert "flat_startup" not in eligible_archetypes(config, 3000)
    assert "enterprise" in eligible_archetypes(config, 6000)
    picks = Counter(select_archetype(config, "technology", "small", 150, Rng(i)) for i in range(200))
    assert set(picks) <= set(eligible_archetypes(config, 150))
    assert len(picks) >= 3


def test_department_tree(tech_company: CompanyRecords) -> None:
    depts = {d.department_id: d for d in tech_company.departments}
    assert sum(1 for d in depts.values() if d.department_type is DepartmentType.EXECUTIVE) == 1
    assert any(d.department_type is DepartmentType.SUB_FUNCTION for d in depts.values())
    for dept in depts.values():
        if dept.parent_department_id is not None:
            assert dept.parent_department_id in depts
    assert not find_cycles({d.department_id: d.parent_department_id for d in depts.values()})
    names = {d.department_name for d in depts.values()}
    assert "Engineering" in names


def test_departments_depend_on_industry(builder: CompanyBuilder) -> None:
    bank = builder.build(make_plan(index=2, industry="banking", employee_count=420))
    plant = builder.build(make_plan(index=3, industry="manufacturing", employee_count=420))
    bank_names = {d.department_name for d in bank.departments}
    plant_names = {d.department_name for d in plant.departments}
    assert "Risk" in bank_names and "Commercial Banking" in bank_names
    assert "Manufacturing Operations" in plant_names
    assert "Commercial Banking" not in plant_names


def test_hierarchy_is_a_single_rooted_tree(tech_company: CompanyRecords) -> None:
    edges = tech_company.reporting_edges
    assert len(edges) == len(tech_company.employees) == tech_company.company.employee_count
    roots = [e for e in edges if e.manager_employee_id is None]
    assert len(roots) == 1
    parent = {e.employee_id: e.manager_employee_id for e in edges}
    assert not find_cycles(parent)
    employee_ids = {e.employee_id for e in tech_company.employees}
    assert all(m in employee_ids for m in parent.values() if m)


def test_managers_outrank_reports(tech_company: CompanyRecords) -> None:
    seniority = {e.employee_id: e.seniority_level.value for e in tech_company.employees}
    for edge in tech_company.reporting_edges:
        if edge.manager_employee_id:
            assert (
                SENIORITY_RANK[seniority[edge.manager_employee_id]]
                >= SENIORITY_RANK[seniority[edge.employee_id]]
            )


def test_workforce_pyramid(builder: CompanyBuilder) -> None:
    records = builder.build(make_plan(index=4, employee_count=3000, archetype="functional"))
    levels = Counter(e.seniority_level.value for e in records.employees)
    ics = sum(levels[lvl] for lvl in ("intern", "junior", "ic", "senior_ic", "staff", "principal"))
    managers = levels["manager"] + levels["senior_manager"]
    directors = levels["director"] + levels["senior_director"]
    vps = levels["vp"] + levels["svp"]
    assert ics > managers > directors >= vps
    spans = list(_children(records).values())
    assert len(set(spans)) > 5, "spans of control must vary"
    leaf_seniors = {
        e.employee_id for e in records.employees if e.seniority_level.value in ("staff", "principal")
    }
    assert leaf_seniors - set(_children(records)), "senior ICs without reports exist"


@pytest.mark.parametrize(
    ("archetype", "size"), [("flat_startup", 180), ("functional", 900), ("enterprise", 8000)]
)
def test_depth_grows_with_size_and_archetype(builder: CompanyBuilder, archetype: str, size: int) -> None:
    records = builder.build(make_plan(index=5, archetype=archetype, employee_count=size))
    depth = records.stats["max_depth"]
    low, high = {"flat_startup": (2, 5), "functional": (3, 7), "enterprise": (6, 11)}[archetype]
    assert low <= depth <= high


def test_segmented_archetypes_create_segment_heads(builder: CompanyBuilder) -> None:
    bu = builder.build(make_plan(index=6, archetype="business_unit", employee_count=2500))
    titles = Counter(e.canonical_title for e in bu.employees)
    assert titles["Business Unit President"] >= 2
    assert any(d.department_type is DepartmentType.BUSINESS_UNIT for d in bu.departments)

    regional = builder.build(make_plan(index=7, archetype="regional", employee_count=1500))
    assert Counter(e.canonical_title for e in regional.employees)["Regional President"] >= 2

    enterprise = builder.build(
        make_plan(index=8, archetype="enterprise", employee_count=9000, industry="banking")
    )
    etitles = Counter(e.canonical_title for e in enterprise.employees)
    assert etitles["Business Unit President"] >= 2 and etitles["Division President"] >= 4


def test_matrix_secondary_edges_are_separate(builder: CompanyBuilder) -> None:
    records = builder.build(make_plan(index=9, archetype="matrix", employee_count=1500))
    assert records.secondary_edges
    primary = {e.employee_id: e.manager_employee_id for e in records.reporting_edges}
    for sec in records.secondary_edges:
        assert sec.manager_employee_id != primary[sec.employee_id]
        assert sec.manager_employee_id != sec.employee_id


def test_positions_mirror_hierarchy(tech_company: CompanyRecords) -> None:
    positions = {p.position_id: p for p in tech_company.positions}
    holder = {e.position_id: e.employee_id for e in tech_company.employees}
    by_employee = {e.employee_id: e for e in tech_company.employees}
    for edge in tech_company.reporting_edges:
        pos = positions[by_employee[edge.employee_id].position_id]
        assert pos.organizational_level == edge.hierarchy_depth
        expected = holder[pos.parent_position_id] if pos.parent_position_id else None
        assert expected == edge.manager_employee_id
