# Canonical title taxonomy built from configuration
from __future__ import annotations

import re
from dataclasses import dataclass

from orggraph_dataset.config import ConfigError, OrgGraphConfig
from orggraph_dataset.constants import MANAGEMENT_LEVELS, SENIORITY_ORDER, SENIORITY_RANK
from orggraph_dataset.taxonomy.departments import DepartmentCatalog
from orggraph_dataset.taxonomy.job_families import JobFamilyRegistry

_WS = re.compile(r"\s+")


def normalize_title(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


@dataclass(frozen=True)
class CanonicalTitle:
    canonical_title: str
    job_family: str
    seniority_level: str
    organizational_level: int
    department_compatibility: tuple[str, ...]
    industry_compatibility: tuple[str, ...]
    is_management: bool
    is_executive: bool
    title_variants: tuple[str, ...]
    legacy_titles: tuple[str, ...]
    executive_role: str | None = None


class TitleTaxonomy:
    def __init__(self, config: OrgGraphConfig) -> None:
        self._config = config
        self.families = JobFamilyRegistry(config)
        self.departments = DepartmentCatalog(config)
        self._tiers = {lvl.key: lvl for lvl in config.titles.seniority_levels}
        self._by_title: dict[str, CanonicalTitle] = {}
        self._by_family_level: dict[tuple[str, str], CanonicalTitle] = {}
        self._by_exec_role: dict[str, CanonicalTitle] = {}
        self._build()
        self._variant_index: dict[str, set[str]] = {}
        self._index_variants()

    def _build(self) -> None:
        titles = self._config.titles
        all_industries = tuple(self._config.industries.industries)
        for family_key in self.families.keys():  # noqa: SIM118
            family = self.families.get(family_key)
            tokens = {
                "ic_role": family.ic_role,
                "ic_abbrev": family.ic_abbrev,
                "function": family.function,
                "function_abbrev": family.function_abbrev,
            }
            departments = tuple(self.departments.departments_for_family(family_key))
            for level in self.families.levels(family_key):
                override = titles.override_for(family_key, level)
                if override is not None:
                    title = override.title
                    variants = list(override.variants)
                else:
                    title = titles.ladder_patterns[level].format(**tokens)
                    variants = [p.format(**tokens) for p in titles.variant_patterns.get(level, [])]
                legacy = tuple(family.legacy_titles.get(level, []))
                tier = self._tiers[level]
                self._register(
                    CanonicalTitle(
                        canonical_title=title,
                        job_family=family_key,
                        seniority_level=level,
                        organizational_level=tier.tier,
                        department_compatibility=departments,
                        industry_compatibility=self.families.industries(family_key),
                        is_management=tier.management,
                        is_executive=tier.executive,
                        title_variants=_dedupe(title, variants),
                        legacy_titles=legacy,
                    )
                )
        for role_key, role in titles.executive_roles.items():
            departments = tuple(self.departments.departments_for_executive(role_key))
            if role_key == "ceo":
                departments = ("executive_office",)
            tier = self._tiers[role.seniority]
            entry = CanonicalTitle(
                canonical_title=role.title,
                job_family="executive",
                seniority_level=role.seniority,
                organizational_level=tier.tier,
                department_compatibility=departments,
                industry_compatibility=all_industries,
                is_management=True,
                is_executive=True,
                title_variants=_dedupe(role.title, role.variants),
                legacy_titles=(),
                executive_role=role_key,
            )
            self._register(entry)
            self._by_exec_role[role_key] = entry

    def _register(self, entry: CanonicalTitle) -> None:
        key = normalize_title(entry.canonical_title)
        if key in self._by_title:
            other = self._by_title[key]
            raise ConfigError(
                f"canonical title collision: '{entry.canonical_title}' is produced by "
                f"{other.job_family}/{other.seniority_level} and "
                f"{entry.job_family}/{entry.seniority_level}; add an override in title_taxonomy.yaml"
            )
        self._by_title[key] = entry
        if entry.executive_role is None:
            self._by_family_level[(entry.job_family, entry.seniority_level)] = entry

    def _index_variants(self) -> None:
        for entry in self._by_title.values():
            for text in (*entry.title_variants, *entry.legacy_titles):
                self._variant_index.setdefault(normalize_title(text), set()).add(entry.canonical_title)

    def all_titles(self) -> list[CanonicalTitle]:
        return list(self._by_title.values())

    def entry(self, canonical_title: str) -> CanonicalTitle:
        return self._by_title[normalize_title(canonical_title)]

    def title_for(self, family: str, level: str) -> CanonicalTitle:
        resolved = self.families.nearest_level(family, level)
        return self._by_family_level[(family, resolved)]

    def executive_title(self, role: str) -> CanonicalTitle:
        return self._by_exec_role[role]

    def resolve_variant(self, text: str) -> str | None:
        key = normalize_title(text)
        if key in self._by_title:
            return self._by_title[key].canonical_title
        candidates = self._variant_index.get(key)
        if candidates and len(candidates) == 1:
            return next(iter(candidates))
        return None

    def ambiguous_variants(self) -> dict[str, list[str]]:
        return {
            variant: sorted(canonicals)
            for variant, canonicals in self._variant_index.items()
            if len(canonicals) > 1
            or (variant in self._by_title and canonicals - {self._by_title[variant].canonical_title})
        }

    def previous_title(self, entry: CanonicalTitle) -> CanonicalTitle | None:
        if entry.executive_role is not None:
            return None
        family = entry.job_family
        levels = self.families.levels(family)
        level = entry.seniority_level
        if level == "manager":
            return self.title_for(family, "senior_ic")
        index = levels.index(level)
        if index == 0:
            return None
        return self._by_family_level[(family, levels[index - 1])]

    def adjacent_title(self, entry: CanonicalTitle, step: int) -> CanonicalTitle | None:
        if entry.executive_role is not None:
            return None
        levels = self.families.levels(entry.job_family)
        band = [
            lvl
            for lvl in levels
            if (lvl in MANAGEMENT_LEVELS) == (entry.seniority_level in MANAGEMENT_LEVELS)
        ]
        index = band.index(entry.seniority_level) + step
        if 0 <= index < len(band):
            return self._by_family_level[(entry.job_family, band[index])]
        return None

    @staticmethod
    def seniority_rank(level: str) -> int:
        return SENIORITY_RANK[level]

    @staticmethod
    def seniority_levels() -> tuple[str, ...]:
        return SENIORITY_ORDER


def _dedupe(title: str, variants: list[str]) -> tuple[str, ...]:
    seen = {normalize_title(title)}
    ordered = [title]
    for variant in variants:
        key = normalize_title(variant)
        if key and key not in seen:
            seen.add(key)
            ordered.append(variant)
    return tuple(ordered)
