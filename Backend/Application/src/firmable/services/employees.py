# Employee listing, details and cross-company search
from __future__ import annotations

import builtins
import json
import threading
from dataclasses import dataclass

from orggraph_inference.features import EmployeeProfile

from firmable.core.errors import NotFoundError
from firmable.schemas.common import Page, paginate
from firmable.schemas.employees import (
    CandidateOut,
    EmployeeDetail,
    EmployeeRef,
    EmployeeSummary,
    ObservationOut,
    SearchHit,
)
from firmable.services.datasets import DatasetService
from firmable.services.inference import CompanyView, InferenceService


@dataclass(frozen=True)
class _IndexEntry:
    employee_id: str
    company_id: str
    company_name: str
    full_name: str
    split: str
    haystack: str


class EmployeeService:
    def __init__(self, datasets: DatasetService, inference: InferenceService) -> None:
        self.datasets = datasets
        self.inference = inference
        self._index: dict[str, builtins.list[_IndexEntry]] = {}
        self._lock = threading.Lock()

    def invalidate(self, dataset_id: str) -> None:
        with self._lock:
            self._index.pop(dataset_id, None)

    @staticmethod
    def ref(view: CompanyView, employee_id: str) -> EmployeeRef:
        profile = view.inference.profiles[employee_id]
        return EmployeeRef(
            employee_id=employee_id,
            full_name=view.names.get(employee_id, employee_id),
            title=profile.canonical_title or profile.title,
            seniority=profile.seniority,
        )

    @staticmethod
    def summary(view: CompanyView, profile: EmployeeProfile) -> EmployeeSummary:
        decision = view.inference.graph.decisions[profile.employee_id]
        manager = view.edges.get(profile.employee_id)
        return EmployeeSummary(
            employee_id=profile.employee_id,
            company_id=view.company.company_id,
            full_name=view.names.get(profile.employee_id, profile.employee_id),
            title=profile.title,
            seniority=profile.seniority,
            employment_type=view.employment_types.get(profile.employee_id, "unknown"),
            inferred_title=profile.canonical_title,
            job_family=profile.job_family,
            department=profile.department_name or profile.department_key,
            region=profile.region,
            departed=profile.departed,
            predicted_manager_id=manager,
            confidence=decision.confidence if manager else 0.0,
            direct_reports=len(view.children.get(profile.employee_id, [])),
        )

    def list(
        self,
        dataset_id: str,
        company_id: str,
        page: int,
        page_size: int,
        q: str | None = None,
        department: str | None = None,
        seniority: str | None = None,
        resolved: bool | None = None,
        include_departed: bool = True,
    ) -> Page[EmployeeSummary]:
        view = self.inference.company(dataset_id, company_id)
        needle = q.lower().strip() if q else None
        rows = []
        for profile in view.inference.profiles.values():
            if not include_departed and profile.departed:
                continue
            if seniority and profile.seniority != seniority:
                continue
            if department and department.lower() not in {
                (profile.department_name or "").lower(),
                (profile.department_key or "").lower(),
                (profile.department_top_key or "").lower(),
            }:
                continue
            is_resolved = profile.employee_id in view.edges
            if resolved is not None and resolved != is_resolved:
                continue
            if needle:
                haystack = " ".join(
                    (
                        view.names.get(profile.employee_id, ""),
                        profile.title or "",
                        profile.canonical_title or "",
                        profile.employee_id,
                    )
                ).lower()
                if needle not in haystack:
                    continue
            rows.append(profile)
        rows.sort(key=lambda p: (-p.rank, view.names.get(p.employee_id, "")))
        chunk = paginate(rows, page, page_size)
        return Page[EmployeeSummary](
            items=[self.summary(view, p) for p in chunk.items],
            total=chunk.total,
            page=page,
            page_size=page_size,
        )

    def detail(self, dataset_id: str, company_id: str, employee_id: str) -> EmployeeDetail:
        view = self.inference.company(dataset_id, company_id)
        profile = view.inference.profiles.get(employee_id)
        if profile is None:
            raise NotFoundError(f"employee '{employee_id}' not found in company '{company_id}'")
        decision = view.inference.graph.decisions[employee_id]
        manager_id = view.edges.get(employee_id)
        chain: list[EmployeeRef] = []
        seen = {employee_id}
        current = manager_id
        while current and current not in seen and len(chain) < 30:
            chain.append(self.ref(view, current))
            seen.add(current)
            current = view.edges.get(current)
        prediction = next(p for p in view.inference.predictions if p.employee_id == employee_id)
        candidates = []
        for item in prediction.evidence:
            if item.get("type") == "candidates":
                for top in item["top"]:
                    cand = view.inference.profiles.get(top["employee_id"])
                    candidates.append(
                        CandidateOut(
                            employee_id=top["employee_id"],
                            full_name=view.names.get(top["employee_id"]),
                            title=(cand.canonical_title or cand.title) if cand else None,
                            probability=top["probability"],
                        )
                    )
        observations = sorted(
            view.observations.get(employee_id, []),
            key=lambda o: (o.observed_at is None, o.observed_at),
            reverse=True,
        )
        return EmployeeDetail(
            **self.summary(view, profile).model_dump(),
            segment=profile.segment,
            city=profile.city,
            seniority_confidence=round(profile.seniority_confidence, 3),
            department_confidence=round(profile.department_confidence, 3),
            departed_confidence=profile.departed_confidence,
            sources=profile.sources,
            decision_reason=decision.reason,
            manager=self.ref(view, manager_id) if manager_id else None,
            reports=[self.ref(view, r) for r in view.children.get(employee_id, [])],
            chain_of_command=chain,
            candidates=candidates,
            evidence=prediction.evidence,
            observations=[
                ObservationOut(
                    observation_id=o.observation_id,
                    source=o.source.value if o.source else None,
                    observed_title=o.observed_title,
                    observed_department=o.observed_department,
                    observed_job_family=o.observed_job_family,
                    observed_location=o.observed_location,
                    observed_at=o.observed_at,
                    employment_status=o.employment_status.value,
                    historical_manager_id=o.historical_manager_id,
                    missing_fields=o.missing_fields,
                )
                for o in observations
            ],
        )

    def _search_index(self, dataset_id: str) -> builtins.list[_IndexEntry]:
        reader = self.datasets.reader(dataset_id)
        with self._lock:
            if dataset_id in self._index:
                return self._index[dataset_id]
        entries: builtins.list[_IndexEntry] = []
        for split in reader.splits():
            names = {c.company_id: c.company_name for c in reader.iter_company_rows(split)}
            with reader.path(split, "employees").open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    entries.append(
                        _IndexEntry(
                            employee_id=row["employee_id"],
                            company_id=row["company_id"],
                            company_name=names.get(row["company_id"], row["company_id"]),
                            full_name=row["full_name"],
                            split=split,
                            haystack=f"{row['full_name']} {row['employee_id']}".lower(),
                        )
                    )
        with self._lock:
            self._index[dataset_id] = entries
        return entries

    def search(
        self, dataset_id: str, q: str, page: int, page_size: int, company_id: str | None = None
    ) -> Page[SearchHit]:
        needle = q.lower().strip()
        hits = [
            e
            for e in self._search_index(dataset_id)
            if needle in e.haystack and (company_id is None or e.company_id == company_id)
        ]
        hits.sort(key=lambda e: (not e.full_name.lower().startswith(needle), e.full_name, e.company_id))
        chunk = paginate(hits, page, page_size)
        return Page[SearchHit](
            items=[
                SearchHit(
                    employee_id=e.employee_id,
                    company_id=e.company_id,
                    company_name=e.company_name,
                    full_name=e.full_name,
                    split=e.split,
                )
                for e in chunk.items
            ],
            total=chunk.total,
            page=page,
            page_size=page_size,
        )
