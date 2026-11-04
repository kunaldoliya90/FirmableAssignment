# Company and org-chart response models
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CompanySummary(BaseModel):
    company_id: str
    company_name: str
    industry: str
    employee_count: int
    company_size_segment: str
    headquarters: str
    operating_regions: list[str]
    split: str
    inferred: bool


class CompanyDetail(CompanySummary):
    observed_employee_count: int
    observation_count: int
    observations_by_source: dict[str, int]
    inference: dict[str, Any] | None
