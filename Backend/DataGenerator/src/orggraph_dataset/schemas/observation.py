# Employee observations (observed) and their hidden noise labels (ground truth)
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orggraph_dataset.schemas.enums import EmploymentStatus, Source


class EmployeeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str
    employee_id: str
    company_id: str
    observed_title: str | None
    observed_department: str | None
    observed_job_family: str | None
    observed_location: str | None
    source: Source | None
    observed_at: datetime | None
    employment_status: EmploymentStatus
    historical_manager_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class ObservationLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str
    employee_id: str
    company_id: str
    canonical_title: str
    canonical_department: str
    true_source: Source
    noise_applied: list[str]
    is_stale: bool
    is_departed_employee: bool
    historical_manager_is_current: bool | None = None
