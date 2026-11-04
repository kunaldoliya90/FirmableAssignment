# Canonical department records (ground truth only)
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orggraph_dataset.schemas.enums import DepartmentType


class Department(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    department_id: str
    company_id: str
    department_name: str = Field(min_length=1)
    department_type: DepartmentType
    parent_department_id: str | None
    department_key: str
