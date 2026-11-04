# Reporting-hierarchy construction from the department blueprint
from __future__ import annotations

import math
from dataclasses import dataclass

from orggraph_dataset.config import ArchetypeConfig, OrgGraphConfig
from orggraph_dataset.constants import MANAGEMENT_LEVELS, SENIORITY_RANK
from orggraph_dataset.generators.department_generator import DeptUnit, OrgBlueprint, SegmentUnit
from orggraph_dataset.schemas import Department
from orggraph_dataset.taxonomy import TitleTaxonomy
from orggraph_dataset.utils.random_utils import Rng, split_with_minimum


@dataclass
class OrgNode:
    index: int
    parent: int | None
    seniority: str
    family: str
    exec_role: str | None
    department: Department
    department_key: str
    role: str
    depth: int
    segment_names: tuple[str, ...]
    region_key: str | None


@dataclass
class OrgTree:
    nodes: list[OrgNode]
    secondary: list[tuple[int, int]]

    @property
    def max_depth(self) -> int:
        return max(node.depth for node in self.nodes)

    def children_counts(self) -> list[int]:
        counts = [0] * len(self.nodes)
        for node in self.nodes:
            if node.parent is not None:
                counts[node.parent] += 1
        return counts


class HierarchyGenerator:
    def __init__(self, config: OrgGraphConfig, taxonomy: TitleTaxonomy) -> None:
        self._config = config
        self._taxonomy = taxonomy

    def generate(
        self,
        blueprint: OrgBlueprint,
        employee_count: int,
        industry: str,
        archetype: ArchetypeConfig,
        rng: Rng,
    ) -> OrgTree:
        builder = _TreeBuilder(self._config, self._taxonomy, industry, archetype, employee_count, rng)
        tree = builder.build(blueprint)
        if len(tree.nodes) != employee_count:
            raise RuntimeError(f"hierarchy has {len(tree.nodes)} positions, expected {employee_count}")
        return tree


class _TreeBuilder:
    def __init__(
        self,
        config: OrgGraphConfig,
        taxonomy: TitleTaxonomy,
        industry: str,
        archetype: ArchetypeConfig,
        employee_count: int,
        rng: Rng,
    ) -> None:
        self.cfg = config
        self.tax = taxonomy
        self.families = taxonomy.families
        self.catalog = taxonomy.departments
        self.industry = industry
        self.arch = archetype
        self.n = employee_count
        self.rng = rng
        self.workforce = config.dataset.workforce
        self.levels = [lvl for lvl in MANAGEMENT_LEVELS if lvl in archetype.levels]
        self.thresholds = {
            lvl: 2
            if lvl == self.levels[0]
            else max(2, round(archetype.level_min_headcount[lvl] * archetype.level_size_scale))
            for lvl in self.levels
        }
        self.team_target = sum(archetype.ic_team_size) / 2
        self.nodes: list[OrgNode] = []

    def add(
        self,
        parent: int | None,
        seniority: str,
        family: str,
        department: Department,
        department_key: str,
        role: str,
        segments: tuple[str, ...],
        region: str | None,
        exec_role: str | None = None,
    ) -> int:
        depth = 0 if parent is None else self.nodes[parent].depth + 1
        index = len(self.nodes)
        self.nodes.append(
            OrgNode(
                index,
                parent,
                seniority,
                family,
                exec_role,
                department,
                department_key,
                role,
                depth,
                segments,
                region,
            )
        )
        return index

    def below(self, level: str) -> str | None:
        rank = SENIORITY_RANK[level]
        lower = [lvl for lvl in self.levels if SENIORITY_RANK[lvl] < rank]
        return lower[-1] if lower else None

    def head_level(self, headcount: int, cap: str) -> str:
        cap_rank = SENIORITY_RANK[cap]
        allowed = [lvl for lvl in self.levels if SENIORITY_RANK[lvl] <= cap_rank] or self.levels[:1]
        for lvl in reversed(allowed):
            if headcount >= self.thresholds[lvl]:
                return lvl
        return allowed[0]

    def unit_families(self, key: str) -> dict[str, float]:
        families = {
            fam: weight
            for fam, weight in self.catalog.entry(key).families.items()
            if self.families.is_compatible(fam, self.industry)
        }
        return families or {self.catalog.entry(key).management_family: 1.0}

    def management_family(self, key: str) -> str:
        managed = {f: w for f, w in self.unit_families(key).items() if self.families.has_management(f)}
        if not managed:
            return self.catalog.entry(key).management_family
        return self.rng.weighted_key(managed)

    def ic_level(self, family: str, mix: dict[str, float]) -> str:
        return self.families.nearest_level(family, self.rng.weighted_key(mix))

    def build(self, blueprint: OrgBlueprint) -> OrgTree:
        eo = blueprint.executive_office
        ceo = self.add(
            None, "c_level", "executive", eo.department, "executive_office", "ceo", (), None, "ceo"
        )
        for i in range(eo.direct_headcount):
            level = "staff" if i == 1 and self.n >= 500 else ("senior_ic" if i >= 2 else "ic")
            self.add(
                ceo,
                self.families.nearest_level("executive_support", level),
                "executive_support",
                eo.department,
                "executive_office",
                "support",
                (),
                None,
            )

        self.build_corporate(ceo, blueprint.corporate)
        for segment in blueprint.segments:
            self.build_segment(ceo, segment, ())
        secondary = self.build_secondary()
        return OrgTree(nodes=self.nodes, secondary=secondary)

    def build_corporate(self, ceo: int, units: list[DeptUnit]) -> None:
        groups: dict[str, list[DeptUnit]] = {}
        for unit in units:
            role = self._executive_for(unit.key)
            groups.setdefault(role or f"__none__{unit.key}", []).append(unit)
        exec_layer = self.n >= self.arch.exec_layer_min_employees
        top_cap = self.arch.corporate_head_cap if exec_layer else self.arch.small_company_head_cap
        for role, group in groups.items():
            group_headcount = sum(u.headcount for u in group)
            has_exec = not role.startswith("__none__") and (
                exec_layer or group_headcount >= self.arch.exec_min_group_headcount
            )
            if not has_exec:
                for unit in group:
                    self.build_unit(ceo, unit, top_cap, (), None)
                continue
            if len(group) == 1:
                unit = group[0]
                head = self.add(
                    ceo,
                    "c_level",
                    "executive",
                    unit.department,
                    unit.key,
                    "executive",
                    (),
                    None,
                    role,
                )
                self.build_unit_body(head, unit, "c_level", (), None)
                continue
            largest = max(group, key=lambda u: u.headcount)
            largest.take_one()
            head = self.add(
                ceo,
                "c_level",
                "executive",
                largest.department,
                largest.key,
                "executive",
                (),
                None,
                role,
            )
            cap = self.below("c_level") or self.levels[0]
            for unit in group:
                self.build_unit(head, unit, cap, (), None)

    def _executive_for(self, key: str) -> str | None:
        override = self.cfg.industries.industries[self.industry].executive_overrides.get(key)
        return override or self.tax.departments.top_level(key).executive

    def build_segment(self, parent: int, segment: SegmentUnit, names: tuple[str, ...]) -> None:
        seniority = self.cfg.titles.executive_roles[segment.head_role].seniority
        scope = (*names, segment.name)
        head = self.add(
            parent,
            seniority,
            "executive",
            segment.department,
            segment.kind,
            "segment_head",
            scope,
            segment.region_key,
            segment.head_role,
        )
        for child in segment.children:
            self.build_segment(head, child, scope)
        cap = self.below(seniority) or self.levels[0]
        for unit in segment.departments:
            self.build_unit(head, unit, cap, scope, segment.region_key)

    def build_unit(
        self, parent: int, unit: DeptUnit, cap: str, scope: tuple[str, ...], region: str | None
    ) -> None:
        level = self.head_level(unit.headcount, cap)
        family = self.catalog.entry(unit.key).management_family
        head = self.add(parent, level, family, unit.department, unit.key, "unit_head", scope, region)
        self.build_unit_body(head, unit, level, scope, region)

    def build_unit_body(
        self, head: int, unit: DeptUnit, level: str, scope: tuple[str, ...], region: str | None
    ) -> None:
        child_cap = self.below(level)
        for sub in unit.subunits:
            if child_cap is None:
                self.build_team(head, sub, sub.headcount, None, scope, region)
            else:
                self.build_unit(head, sub, child_cap, scope, region)
        self.build_people(head, unit, unit.direct_headcount, level, self.nodes[head].family, scope, region)

    def build_people(
        self,
        head: int,
        unit: DeptUnit,
        n: int,
        level: str,
        family: str,
        scope: tuple[str, ...],
        region: str | None,
    ) -> None:
        if n <= 0:
            return
        child_cap = self.below(level)
        low, high = self.arch.ic_team_size
        if child_cap is None or n <= self.rng.randint(low, high):
            self.build_team(head, unit, n, family, scope, region)
            return

        if SENIORITY_RANK[level] >= SENIORITY_RANK["director"] and self.rng.bernoulli(
            self.arch.leader_direct_ic_probability
        ):
            direct = min(self.rng.randint(1, 2), n - 4)
            for _ in range(max(direct, 0)):
                fam = family if family != "executive" else self.management_family(unit.key)
                self.add(
                    head,
                    self.ic_level(fam, self.workforce.leader_direct_ic_mix),
                    fam,
                    unit.department,
                    unit.key,
                    "ic",
                    scope,
                    region,
                )
            n -= max(direct, 0)

        span_low, span_high = self.arch.span_of_control.get(level, (2, 6))
        k = min(max(math.ceil(n / self.team_target), 2), self.rng.randint(span_low, span_high))
        if self.head_level(math.ceil(n / max(k, 1)), child_cap) == self.levels[0]:
            max_team = self.arch.manager_max_team_size
            if self.rng.bernoulli(self.arch.large_span_probability):
                max_team *= 2
            k = max(k, math.ceil(n / (max_team + 1)))
        k = min(k, n // 2)
        if k < 2:
            self.build_team(head, unit, n, family, scope, region)
            return
        for size in split_with_minimum(self.rng, n, k, 2, 2.5):
            child_level = self.head_level(size, child_cap)
            child_family = self.management_family(unit.key)
            child = self.add(
                head, child_level, child_family, unit.department, unit.key, "manager", scope, region
            )
            self.build_people(child, unit, size - 1, child_level, child_family, scope, region)

    def build_team(
        self,
        head: int,
        unit: DeptUnit,
        n: int,
        family: str | None,
        scope: tuple[str, ...],
        region: str | None,
    ) -> None:
        families = self.unit_families(unit.key)
        primary = family if family in families else self.rng.weighted_key(families)
        secondary = None
        others = {f: w for f, w in families.items() if f != primary}
        if others and self.rng.bernoulli(self.workforce.mixed_team_probability):
            secondary = self.rng.weighted_key(others)
        for _ in range(n):
            fam = secondary if secondary and self.rng.bernoulli(0.3) else primary
            self.add(
                head,
                self.ic_level(fam, self.workforce.ic_seniority_mix),
                fam,
                unit.department,
                unit.key,
                "ic",
                scope,
                region,
            )

    def build_secondary(self) -> list[tuple[int, int]]:
        probability = self.arch.secondary_reporting_probability
        if probability <= 0:
            return []

        def top_key(key: str) -> str:
            if key not in self.catalog:
                return key
            return self.catalog.entry(key).parent_key or key

        member_depts = set(self.arch.secondary_member_departments)
        manager_depts = set(self.arch.secondary_manager_departments)
        candidates = [
            node.index
            for node in self.nodes
            if top_key(node.department_key) in manager_depts
            and SENIORITY_RANK[node.seniority] >= SENIORITY_RANK["manager"]
        ]
        if not candidates:
            return []
        candidate_ancestors = {c: set(self._ancestors(c)) for c in candidates}
        edges: list[tuple[int, int]] = []
        for node in self.nodes:
            if node.parent is None or top_key(node.department_key) not in member_depts:
                continue
            if not self.rng.bernoulli(probability):
                continue
            for _ in range(8):
                choice = self.rng.choice(candidates)
                if choice not in (node.index, node.parent) and node.index not in candidate_ancestors[choice]:
                    edges.append((node.index, choice))
                    break
        return edges

    def _ancestors(self, index: int) -> list[int]:
        chain: list[int] = []
        parent = self.nodes[index].parent
        while parent is not None:
            chain.append(parent)
            parent = self.nodes[parent].parent
        return chain
