# Department catalog: lookups over departments and sub-departments, with observed name variants
from __future__ import annotations

from dataclasses import dataclass

from orggraph_dataset.config import DepartmentConfig, OrgGraphConfig


@dataclass(frozen=True)
class DepartmentEntry:
    key: str
    name: str
    families: dict[str, float]
    management_family: str
    abbreviations: tuple[str, ...]
    aliases: tuple[str, ...]
    parent_key: str | None
    executive: str | None


class DepartmentCatalog:
    def __init__(self, config: OrgGraphConfig) -> None:
        self._top: dict[str, DepartmentConfig] = dict(config.departments.departments)
        self._entries: dict[str, DepartmentEntry] = {}
        for key, dept in self._top.items():
            self._entries[key] = DepartmentEntry(
                key=key,
                name=dept.name,
                families=dict(dept.families),
                management_family=dept.primary_family,
                abbreviations=tuple(dept.abbreviations),
                aliases=tuple(dept.aliases),
                parent_key=None,
                executive=dept.executive,
            )
            for sub in dept.subdepartments:
                families = dict(sub.families) if sub.families else dict(dept.families)
                management = max(families, key=lambda k: families[k]) if sub.families else dept.primary_family
                self._entries[sub.key] = DepartmentEntry(
                    key=sub.key,
                    name=sub.name,
                    families=families,
                    management_family=management,
                    abbreviations=tuple(sub.abbreviations),
                    aliases=tuple(sub.aliases),
                    parent_key=key,
                    executive=dept.executive,
                )

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def top_level(self, key: str) -> DepartmentConfig:
        return self._top[key]

    def entry(self, key: str) -> DepartmentEntry:
        return self._entries[key]

    def entries(self) -> list[DepartmentEntry]:
        return list(self._entries.values())

    def departments_for_family(self, family: str) -> list[str]:
        return [e.key for e in self._entries.values() if family in e.families]

    def departments_for_executive(self, role: str) -> list[str]:
        return [key for key, dept in self._top.items() if dept.executive == role]
