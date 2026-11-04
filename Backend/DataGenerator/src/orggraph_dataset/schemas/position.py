# Positions: the canonical seats of the org chart, generated before any employee exists
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orggraph_dataset.schemas.enums import SeniorityLevel


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    company_id: str
    department_id: str
    canonical_title: str = Field(min_length=1)
    job_family: str
    seniority_level: SeniorityLevel
    organizational_level: int = Field(ge=0)
    parent_position_id: str | None
