# Candidate manager generation and filtering
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass

from orggraph_dataset.constants import SENIORITY_RANK

from orggraph_inference.features.profiles import EmployeeProfile
from orggraph_inference.features.relationship import management_steps

_DIRECTOR = SENIORITY_RANK["director"]


@dataclass(frozen=True)
class _Bucket:
    ranks: list[float]
    members: list[EmployeeProfile]

    @classmethod
    def of(cls, profiles: list[EmployeeProfile]) -> _Bucket:
        ordered = sorted(profiles, key=lambda p: (p.rank, p.employee_id))
        return cls([p.rank for p in ordered], ordered)

    def above(self, rank: float) -> list[EmployeeProfile]:
        return self.members[bisect.bisect_right(self.ranks, rank) :]


def choose_root(active: list[EmployeeProfile]) -> EmployeeProfile | None:
    ceos = [p for p in active if p.is_ceo]
    if ceos:
        return max(ceos, key=lambda p: (p.seniority_confidence, p.observation_count, p.employee_id))
    if not active:
        return None
    top = max(p.rank for p in active)
    leaders = [p for p in active if p.rank == top]
    return leaders[0] if len(leaders) == 1 else None


class CandidateGenerator:
    def __init__(self, max_candidates: int) -> None:
        self.max_candidates = max_candidates

    def generate(
        self, profiles: dict[str, EmployeeProfile], root: EmployeeProfile | None
    ) -> dict[str, list[EmployeeProfile]]:
        active = [p for p in profiles.values() if not p.departed]
        by_sub: dict[str, list[EmployeeProfile]] = defaultdict(list)
        by_top: dict[str, list[EmployeeProfile]] = defaultdict(list)
        by_family: dict[str, list[EmployeeProfile]] = defaultdict(list)
        for p in active:
            if p.department_key:
                by_sub[p.department_key].append(p)
            if p.department_top_key:
                by_top[p.department_top_key].append(p)
            if p.job_family:
                by_family[p.job_family].append(p)
        sub_buckets = {k: _Bucket.of(v) for k, v in by_sub.items()}
        top_buckets = {k: _Bucket.of(v) for k, v in by_top.items()}
        family_buckets = {k: _Bucket.of(v) for k, v in by_family.items()}
        leaders = [p for p in active if p.executive_role is not None or p.rank >= SENIORITY_RANK["executive"]]

        result: dict[str, list[EmployeeProfile]] = {}
        for emp in active:
            if root is not None and emp.employee_id == root.employee_id:
                result[emp.employee_id] = []
                continue
            pool: dict[str, EmployeeProfile] = {}
            buckets: list[_Bucket] = []
            if emp.department_key and emp.department_key != emp.department_top_key:
                buckets.append(sub_buckets[emp.department_key])
            if emp.department_top_key:
                buckets.append(top_buckets[emp.department_top_key])
            elif emp.job_family in family_buckets:
                buckets.append(family_buckets[emp.job_family])
            for bucket in buckets:
                for cand in bucket.above(emp.rank):
                    if management_steps(emp.rank, cand.rank) <= 3:
                        pool.setdefault(cand.employee_id, cand)
            for cand in leaders:
                if cand.rank > emp.rank:
                    pool.setdefault(cand.employee_id, cand)
            if root is not None and root.rank > emp.rank:
                pool.setdefault(root.employee_id, root)
            for manager_id in emp.historical_managers:
                hist = profiles.get(manager_id)
                if hist is not None and not hist.departed and hist.rank > emp.rank:
                    pool.setdefault(manager_id, hist)
            pool.pop(emp.employee_id, None)
            result[emp.employee_id] = self._filter(emp, list(pool.values()))
        return result

    def _filter(self, emp: EmployeeProfile, pool: list[EmployeeProfile]) -> list[EmployeeProfile]:
        if len(pool) <= self.max_candidates:
            return pool

        def prior(cand: EmployeeProfile) -> float:
            score = -management_steps(emp.rank, cand.rank)
            score += 2.0 * (
                cand.department_top_key == emp.department_top_key and emp.department_top_key is not None
            )
            score += 1.5 * (cand.department_key == emp.department_key and emp.department_key is not None)
            score += 1.0 * (cand.segment == emp.segment and emp.segment is not None)
            score += 0.5 * (cand.job_family == emp.job_family and emp.job_family is not None)
            score += 0.3 * (cand.region == emp.region and emp.region is not None)
            score += 5.0 * (cand.employee_id in emp.historical_managers)
            score += 1.0 * (cand.executive_role is not None and emp.rank >= _DIRECTOR)
            score -= 3.0 * (not cand.is_manager_level)
            return score

        return sorted(pool, key=lambda c: (-prior(c), c.employee_id))[: self.max_candidates]
