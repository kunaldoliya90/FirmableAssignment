# Industry catalog: which departments, archetypes and regions each industry favours
from __future__ import annotations

from orggraph_dataset.config import IndustryConfig, OrgGraphConfig


class IndustryCatalog:
    def __init__(self, config: OrgGraphConfig) -> None:
        self._industries: dict[str, IndustryConfig] = dict(config.industries.industries)
        self._departments = config.departments.departments

    def keys(self) -> list[str]:
        return list(self._industries)

    def get(self, key: str) -> IndustryConfig:
        return self._industries[key]

    def weights(self) -> dict[str, float]:
        return {key: ind.weight for key, ind in self._industries.items()}

    def candidate_departments(self, key: str, employee_count: int) -> dict[str, tuple[float, float]]:
        return {
            dept: spec
            for dept, spec in self._industries[key].departments.items()
            if self._departments[dept].min_company_employees <= employee_count
        }

    def executive_for(self, key: str, department_key: str) -> str | None:
        override = self._industries[key].executive_overrides.get(department_key)
        if override:
            return override
        return self._departments[department_key].executive
