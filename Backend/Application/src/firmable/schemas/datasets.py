# Dataset summary, facet and generation request models
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    dataset_id: str
    company_count: int
    employee_count: int
    observation_count: int
    departed_employee_count: int
    generation_timestamp: str
    random_seed: int
    noise_profile: str
    challenge_noise_profile: str
    split_distribution: dict[str, dict[str, int]]
    inferred_splits: list[str]


class DatasetDetail(DatasetSummary):
    dataset_version: str
    schema_version: str
    industry_distribution: dict[str, int]
    company_size_distribution: dict[str, int]
    archetype_distribution: dict[str, int]
    noise_profile_distribution: dict[str, int]


class GenerateDatasetRequest(BaseModel):
    dataset_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", description="Directory name for the new dataset"
    )
    companies: int = Field(default=20, ge=1)
    min_employees_per_company: int = Field(default=100, ge=1)
    target_employees: int = Field(default=2000, ge=1)
    seed: int = 42
    noise_profile: str = "medium_noise"
    challenge_noise_profile: str = "enterprise_complexity"
    overwrite: bool = False


class NoiseProfileInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
