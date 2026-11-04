# Company routes: filtered listing and observed company details
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from firmable.api.deps import PageParam, PageSizeParam, Services
from firmable.schemas.common import Page
from firmable.schemas.companies import CompanyDetail, CompanySummary

router = APIRouter(tags=["companies"])


@router.get(
    "/datasets/{dataset_id}/companies", response_model=Page[CompanySummary], summary="Explore companies"
)
def list_companies(
    dataset_id: str,
    services: Services,
    page: PageParam = 1,
    page_size: PageSizeParam = 25,
    split: Annotated[str | None, Query(description="train, validation, test or challenge")] = None,
    industry: str | None = None,
    size_segment: str | None = None,
    q: Annotated[str | None, Query(description="Name or ID contains")] = None,
    min_employees: Annotated[int | None, Query(ge=0)] = None,
    max_employees: Annotated[int | None, Query(ge=0)] = None,
    sort: Literal["company_name", "employee_count", "industry", "company_id"] = "company_name",
    descending: bool = False,
) -> Page[CompanySummary]:
    return services.companies.list(
        dataset_id,
        page,
        page_size,
        split,
        industry,
        size_segment,
        q,
        min_employees,
        max_employees,
        sort,
        descending,
    )


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}", response_model=CompanyDetail, summary="Company details"
)
def get_company(dataset_id: str, company_id: str, services: Services) -> CompanyDetail:
    return services.companies.detail(dataset_id, company_id)
