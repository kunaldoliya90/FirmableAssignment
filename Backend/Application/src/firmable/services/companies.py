# Company exploration over observed data
from __future__ import annotations

import threading
from collections import Counter

from orggraph_dataset.schemas import ObservedCompany

from firmable.core.errors import NotFoundError
from firmable.schemas.common import Page, paginate
from firmable.schemas.companies import CompanyDetail, CompanySummary
from firmable.services.datasets import DatasetService
from firmable.services.inference import InferenceService

SORT_FIELDS = {"company_name", "employee_count", "industry", "company_id"}


class CompanyService:
    def __init__(self, datasets: DatasetService, inference: InferenceService) -> None:
        self.datasets = datasets
        self.inference = inference
        self._companies: dict[str, list[tuple[str, ObservedCompany]]] = {}
        self._lock = threading.Lock()

    def all(self, dataset_id: str) -> list[tuple[str, ObservedCompany]]:
        reader = self.datasets.reader(dataset_id)
        with self._lock:
            if dataset_id not in self._companies:
                self._companies[dataset_id] = [
                    (split, company)
                    for split in reader.splits()
                    for company in reader.iter_company_rows(split)
                ]
            return self._companies[dataset_id]

    def invalidate(self, dataset_id: str) -> None:
        with self._lock:
            self._companies.pop(dataset_id, None)

    def _summary(self, dataset_id: str, split: str, company: ObservedCompany) -> CompanySummary:
        return CompanySummary(
            **company.model_dump(mode="json"),
            split=split,
            inferred=self.inference.cached(dataset_id, company.company_id) is not None,
        )

    def list(
        self,
        dataset_id: str,
        page: int,
        page_size: int,
        split: str | None = None,
        industry: str | None = None,
        size_segment: str | None = None,
        q: str | None = None,
        min_employees: int | None = None,
        max_employees: int | None = None,
        sort: str = "company_name",
        descending: bool = False,
    ) -> Page[CompanySummary]:
        needle = q.lower().strip() if q else None
        rows = [
            (s, c)
            for s, c in self.all(dataset_id)
            if (split is None or s == split)
            and (industry is None or c.industry.lower() == industry.lower())
            and (size_segment is None or c.company_size_segment.value == size_segment)
            and (needle is None or needle in c.company_name.lower() or needle in c.company_id)
            and (min_employees is None or c.employee_count >= min_employees)
            and (max_employees is None or c.employee_count <= max_employees)
        ]
        field = sort if sort in SORT_FIELDS else "company_name"
        rows.sort(key=lambda r: getattr(r[1], field), reverse=descending)
        page_rows = paginate(rows, page, page_size)
        return Page[CompanySummary](
            items=[self._summary(dataset_id, s, c) for s, c in page_rows.items],
            total=page_rows.total,
            page=page,
            page_size=page_size,
        )

    def facets(self, dataset_id: str) -> dict[str, dict[str, int]]:
        rows = self.all(dataset_id)
        return {
            "split": dict(Counter(s for s, _ in rows)),
            "industry": dict(sorted(Counter(c.industry for _, c in rows).items())),
            "company_size_segment": dict(Counter(c.company_size_segment.value for _, c in rows)),
        }

    def detail(self, dataset_id: str, company_id: str) -> CompanyDetail:
        reader = self.datasets.reader(dataset_id)
        split = reader.split_of(company_id)
        if split is None:
            raise NotFoundError(f"company '{company_id}' not found in dataset '{dataset_id}'")
        data = reader.load_company(company_id, split)
        view = self.inference.cached(dataset_id, company_id)
        return CompanyDetail(
            **data.company.model_dump(mode="json"),
            split=split,
            inferred=view is not None,
            observed_employee_count=len(data.employees),
            observation_count=len(data.observations),
            observations_by_source=dict(
                Counter(o.source.value if o.source else "unknown" for o in data.observations)
            ),
            inference=view.inference.stats if view else None,
        )
