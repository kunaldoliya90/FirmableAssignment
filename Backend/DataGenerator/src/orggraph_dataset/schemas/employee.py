# Employee records: canonical (ground truth), observed projection, and departed employees
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from orggraph_dataset.schemas.enums import EmploymentType, SeniorityLevel


class ObservedEmployee(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_id: str
    company_id: str
    full_name: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    employment_type: EmploymentType


class Employee(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_id: str
    company_id: str
    full_name: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    canonical_title: str = Field(min_length=1)
    canonical_department: str = Field(min_length=1)
    job_family: str
    seniority_level: SeniorityLevel
    location: str
    employment_type: EmploymentType
    position_id: str

    def to_observed(self) -> ObservedEmployee:
        return ObservedEmployee(
            employee_id=self.employee_id,
            company_id=self.company_id,
            full_name=self.full_name,
            first_name=self.first_name,
            last_name=self.last_name,
            employment_type=self.employment_type,
        )


class DepartedEmployee(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_id: str
    company_id: str
    full_name: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    last_canonical_title: str
    last_canonical_department: str
    job_family: str
    seniority_level: SeniorityLevel
    employment_type: EmploymentType
    departed_on: date

    def to_observed(self) -> ObservedEmployee:
        return ObservedEmployee(
            employee_id=self.employee_id,
            company_id=self.company_id,
            full_name=self.full_name,
            first_name=self.first_name,
            last_name=self.last_name,
            employment_type=self.employment_type,
        )
