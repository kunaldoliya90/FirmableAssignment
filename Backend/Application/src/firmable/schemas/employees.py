# Employee profile, detail and search response models
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EmployeeRef(BaseModel):
    employee_id: str
    full_name: str
    title: str | None
    seniority: str | None


class EmployeeSummary(EmployeeRef):
    company_id: str
    employment_type: str
    inferred_title: str | None
    job_family: str | None
    department: str | None
    region: str | None
    departed: bool
    predicted_manager_id: str | None
    confidence: float
    direct_reports: int


class ObservationOut(BaseModel):
    observation_id: str
    source: str | None
    observed_title: str | None
    observed_department: str | None
    observed_job_family: str | None
    observed_location: str | None
    observed_at: datetime | None
    employment_status: str
    historical_manager_id: str | None
    missing_fields: list[str]


class CandidateOut(BaseModel):
    employee_id: str
    full_name: str | None
    title: str | None
    probability: float


class EmployeeDetail(EmployeeSummary):
    segment: str | None
    city: str | None
    seniority_confidence: float
    department_confidence: float
    departed_confidence: float
    sources: list[str]
    decision_reason: str
    manager: EmployeeRef | None
    reports: list[EmployeeRef]
    chain_of_command: list[EmployeeRef]
    candidates: list[CandidateOut]
    evidence: list[dict[str, Any]]
    observations: list[ObservationOut]


class SearchHit(BaseModel):
    employee_id: str
    company_id: str
    company_name: str
    full_name: str
    split: str
