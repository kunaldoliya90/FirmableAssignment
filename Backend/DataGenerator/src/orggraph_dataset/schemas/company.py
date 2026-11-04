# Company records: full ground-truth company and the observed (inference-safe) projection
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orggraph_dataset.schemas.enums import OrgArchetype, SizeSegment, Split


class ObservedCompany(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: str
    company_name: str = Field(min_length=1)
    industry: str
    employee_count: int = Field(ge=1)
    company_size_segment: SizeSegment
    headquarters: str
    operating_regions: list[str] = Field(min_length=1)


class Company(ObservedCompany):
    org_archetype: OrgArchetype
    generation_seed: int
    noise_profile: str
    split: Split

    def to_observed(self) -> ObservedCompany:
        return ObservedCompany.model_validate(self.model_dump(include=set(ObservedCompany.model_fields)))
