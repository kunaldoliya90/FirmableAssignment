# Ground-truth reporting relationships
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orggraph_dataset.schemas.enums import RelationshipType


class ReportingEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: str
    employee_id: str
    manager_employee_id: str | None
    relationship_type: RelationshipType
    hierarchy_depth: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_consistency(self) -> ReportingEdge:
        if self.relationship_type is RelationshipType.SECONDARY:
            raise ValueError("primary reporting edges cannot have relationship_type 'secondary'")
        is_root = self.relationship_type is RelationshipType.ROOT
        if is_root != (self.manager_employee_id is None):
            raise ValueError("root edges must have no manager and non-root edges must have one")
        if is_root != (self.hierarchy_depth == 0):
            raise ValueError("hierarchy_depth must be 0 exactly for the root")
        if self.manager_employee_id == self.employee_id:
            raise ValueError("an employee cannot report to themselves")
        return self


class SecondaryEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: str
    employee_id: str
    manager_employee_id: str
    relationship_type: RelationshipType = RelationshipType.SECONDARY

    @model_validator(mode="after")
    def _check_type(self) -> SecondaryEdge:
        if self.relationship_type is not RelationshipType.SECONDARY:
            raise ValueError("secondary edges must have relationship_type 'secondary'")
        if self.manager_employee_id == self.employee_id:
            raise ValueError("an employee cannot have a dotted line to themselves")
        return self
