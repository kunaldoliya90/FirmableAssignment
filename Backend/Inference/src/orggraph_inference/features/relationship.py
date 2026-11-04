# Pairwise relationship features between an employee and a candidate manager
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

from orggraph_dataset.constants import MANAGEMENT_LEVELS, SENIORITY_RANK

from orggraph_inference.features.profiles import CEO_RANK, EmployeeProfile

_MANAGER_RANK = SENIORITY_RANK["manager"]


@dataclass(frozen=True)
class RelationshipFeatures:
    level_steps: float
    same_department: bool
    same_subdepartment: bool
    subdepartment_conflict: bool
    department_conflict: bool
    same_family: bool
    manages_family: bool
    same_segment: bool
    segment_conflict: bool
    same_region: bool
    same_city: bool
    historical_manager: float
    executive_owns_department: bool
    executive_wrong_function: bool
    ceo_for_top_level: bool
    ceo_for_lower_level: bool
    candidate_generic_title: bool
    candidate_uncertain_seniority: bool
    candidate_not_manager: bool

    def evidence(self) -> list[str]:
        names = [name for name, value in self.__dict__.items() if isinstance(value, bool) and value]
        if self.historical_manager:
            names.append("historical_manager")
        return names


def management_steps(employee_rank: float, manager_rank: float) -> float:
    if manager_rank >= CEO_RANK:
        return 0.0
    if employee_rank < _MANAGER_RANK:
        return max(manager_rank - _MANAGER_RANK, 0.0)
    return max(manager_rank - employee_rank - 1.0, 0.0)


def present_level_steps(employee_rank: float, manager_rank: float, present_ranks: Sequence[float]) -> float:
    low = max(employee_rank, _MANAGER_RANK - 0.5) if employee_rank < _MANAGER_RANK else employee_rank
    start = bisect.bisect_right(present_ranks, low)
    end = bisect.bisect_left(present_ranks, manager_rank)
    return float(max(end - start, 0))


def relationship_features(
    employee: EmployeeProfile,
    candidate: EmployeeProfile,
    executive_departments: dict[str, set[str]],
    present_ranks: Sequence[float] = (),
) -> RelationshipFeatures:
    same_dept = (
        bool(employee.department_top_key) and employee.department_top_key == candidate.department_top_key
    )
    both_depts = bool(employee.department_top_key and candidate.department_top_key)
    employee_sub = employee.department_key != employee.department_top_key
    candidate_sub = candidate.department_key != candidate.department_top_key
    same_sub = same_dept and employee_sub and employee.department_key == candidate.department_key
    sub_conflict = (
        same_dept and employee_sub and candidate_sub and employee.department_key != candidate.department_key
    )
    is_exec = candidate.executive_role is not None and not candidate.is_ceo
    owned = executive_departments.get(candidate.executive_role or "", set())
    exec_owns = is_exec and employee.department_top_key in owned
    exec_wrong = (
        is_exec
        and bool(employee.department_top_key)
        and bool(owned)
        and employee.department_top_key not in owned
    )
    employee_top_level = employee.rank >= SENIORITY_RANK["director"] or employee.executive_role is not None
    candidate_level = candidate.seniority or ""
    return RelationshipFeatures(
        level_steps=(
            present_level_steps(employee.rank, candidate.rank, present_ranks)
            if present_ranks
            else management_steps(employee.rank, candidate.rank)
        ),
        same_department=same_dept,
        same_subdepartment=same_sub,
        subdepartment_conflict=sub_conflict,
        department_conflict=both_depts and not same_dept and not is_exec and not candidate.is_ceo,
        same_family=bool(employee.job_family) and employee.job_family == candidate.job_family,
        manages_family=candidate_level in MANAGEMENT_LEVELS and candidate.job_family == employee.job_family,
        same_segment=bool(employee.segment) and employee.segment == candidate.segment,
        segment_conflict=bool(employee.segment and candidate.segment)
        and employee.segment != candidate.segment,
        same_region=bool(employee.region) and employee.region == candidate.region,
        same_city=bool(employee.city) and employee.city == candidate.city,
        historical_manager=employee.historical_managers.get(candidate.employee_id, 0.0),
        executive_owns_department=exec_owns,
        executive_wrong_function=exec_wrong,
        ceo_for_top_level=candidate.is_ceo and employee_top_level,
        ceo_for_lower_level=candidate.is_ceo and not employee_top_level,
        candidate_generic_title=candidate.generic_title,
        candidate_uncertain_seniority=candidate.seniority_confidence < 0.5,
        candidate_not_manager=candidate.rank < _MANAGER_RANK,
    )
