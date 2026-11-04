# Dataset-level containers and metadata documents
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from orggraph_dataset.schemas.company import Company
from orggraph_dataset.schemas.department import Department
from orggraph_dataset.schemas.employee import DepartedEmployee, Employee, ObservedEmployee
from orggraph_dataset.schemas.observation import EmployeeObservation, ObservationLabel
from orggraph_dataset.schemas.position import Position
from orggraph_dataset.schemas.reporting_edge import ReportingEdge, SecondaryEdge


@dataclass
class CompanyRecords:
    company: Company
    departments: list[Department]
    positions: list[Position]
    employees: list[Employee]
    reporting_edges: list[ReportingEdge]
    secondary_edges: list[SecondaryEdge]
    departed_employees: list[DepartedEmployee]
    observed_employees: list[ObservedEmployee]
    observations: list[EmployeeObservation]
    observation_labels: list[ObservationLabel]
    stats: dict[str, Any] = field(default_factory=dict)


class SplitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    fractions: dict[str, float]
    holdout_industries: list[str]
    splits: dict[str, list[str]]
    company_counts: dict[str, int]
    employee_counts: dict[str, int]


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    schema_version: str
    generator_version: str
    generation_timestamp: str
    random_seed: int
    requested_target_employees: int
    planned_employee_total: int
    company_count: int
    employee_count: int
    departed_employee_count: int
    observation_count: int
    reporting_edge_count: int
    root_count: int
    secondary_edge_count: int
    industry_distribution: dict[str, int]
    company_size_distribution: dict[str, int]
    archetype_distribution: dict[str, int]
    noise_profile: dict[str, Any]
    noise_profile_distribution: dict[str, int]
    split_distribution: dict[str, dict[str, int]]
    output_file_checksums: dict[str, str]
    record_counts: dict[str, int]
