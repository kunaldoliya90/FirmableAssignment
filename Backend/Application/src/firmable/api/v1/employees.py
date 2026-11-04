# Employee routes: listing, details and cross-company search
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from firmable.api.deps import PageParam, PageSizeParam, Services
from firmable.schemas.common import Page
from firmable.schemas.employees import EmployeeDetail, EmployeeSummary, SearchHit

router = APIRouter(tags=["employees"])


@router.get(
    "/datasets/{dataset_id}/employees/search",
    response_model=Page[SearchHit],
    summary="Search employees by name or ID across a dataset",
)
def search_employees(
    dataset_id: str,
    services: Services,
    q: Annotated[str, Query(min_length=2)],
    company_id: str | None = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 25,
) -> Page[SearchHit]:
    return services.employees.search(dataset_id, q, page, page_size, company_id)


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}/employees",
    response_model=Page[EmployeeSummary],
    summary="Employees of a company with inferred profiles (runs inference on first access)",
)
def list_employees(
    dataset_id: str,
    company_id: str,
    services: Services,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    q: str | None = None,
    department: str | None = None,
    seniority: str | None = None,
    resolved: Annotated[
        bool | None, Query(description="Only employees with (or without) a predicted manager")
    ] = None,
    include_departed: bool = True,
) -> Page[EmployeeSummary]:
    return services.employees.list(
        dataset_id, company_id, page, page_size, q, department, seniority, resolved, include_departed
    )


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}/employees/{employee_id}",
    response_model=EmployeeDetail,
    summary="Employee profile, observations, predicted manager, reports and evidence",
)
def get_employee(dataset_id: str, company_id: str, employee_id: str, services: Services) -> EmployeeDetail:
    return services.employees.detail(dataset_id, company_id, employee_id)
