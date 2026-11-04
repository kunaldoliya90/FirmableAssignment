# Job family registry: available ladder levels and industry compatibility
from __future__ import annotations

from orggraph_dataset.config import JobFamilyConfig, OrgGraphConfig
from orggraph_dataset.constants import IC_LEVELS, MANAGEMENT_LEVELS, SENIORITY_RANK


class JobFamilyRegistry:
    def __init__(self, config: OrgGraphConfig) -> None:
        self._families: dict[str, JobFamilyConfig] = dict(config.job_families.families)
        self._all_industries = tuple(config.industries.industries)

    def __contains__(self, key: object) -> bool:
        return key in self._families

    def keys(self) -> list[str]:
        return list(self._families)

    def get(self, key: str) -> JobFamilyConfig:
        return self._families[key]

    def display_name(self, key: str) -> str:
        if key == "executive":
            return "Executive Leadership"
        return self._families[key].name

    def aliases(self, key: str) -> list[str]:
        if key == "executive":
            return ["Executive", "Leadership", "Senior Leadership"]
        return list(self._families[key].aliases)

    def has_management(self, key: str) -> bool:
        return self._families[key].management

    def levels(self, key: str) -> list[str]:
        family = self._families[key]
        levels = [lvl for lvl in IC_LEVELS if lvl in family.ic_levels]
        if family.management:
            levels += list(MANAGEMENT_LEVELS)
        return levels

    def industries(self, key: str) -> tuple[str, ...]:
        family = self._families[key]
        return tuple(family.industries) if family.industries else self._all_industries

    def is_compatible(self, key: str, industry: str) -> bool:
        return industry in self.industries(key)

    def nearest_level(self, key: str, level: str) -> str:
        available = self.levels(key)
        if level in available:
            return level
        rank = SENIORITY_RANK[level]
        if level in MANAGEMENT_LEVELS:
            if not self._families[key].management:
                raise ValueError(f"job family '{key}' has no management ladder")
            return level
        ic_available = [lvl for lvl in available if lvl in IC_LEVELS]
        below = [lvl for lvl in ic_available if SENIORITY_RANK[lvl] < rank]
        if below:
            return below[-1]
        return ic_available[0]
