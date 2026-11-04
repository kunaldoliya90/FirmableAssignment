# Department selection, headcount allocation and the department/segment blueprint
from __future__ import annotations

from dataclasses import dataclass, field

from orggraph_dataset.config import ArchetypeConfig, OrgGraphConfig, SegmentLayerConfig
from orggraph_dataset.generators.archetype_generator import segment_count, segment_names
from orggraph_dataset.generators.company_generator import CompanyContext
from orggraph_dataset.schemas import Company, Department, DepartmentType
from orggraph_dataset.taxonomy import DepartmentCatalog, IndustryCatalog
from orggraph_dataset.utils.ids import department_id
from orggraph_dataset.utils.random_utils import Rng, largest_remainder, split_with_minimum

_SEGMENT_TYPES = {
    "business_unit": DepartmentType.BUSINESS_UNIT,
    "division": DepartmentType.DIVISION,
    "region": DepartmentType.REGION,
    "product_line": DepartmentType.PRODUCT_LINE,
}


@dataclass
class DeptUnit:
    department: Department
    key: str
    headcount: int
    direct_headcount: int
    subunits: list[DeptUnit] = field(default_factory=list)

    def take_one(self) -> None:
        if self.direct_headcount > 0:
            self.direct_headcount -= 1
        elif self.subunits:
            max(self.subunits, key=lambda u: u.headcount).take_one()
        else:
            raise ValueError(f"cannot remove a person from single-person unit {self.key}")
        self.headcount -= 1


@dataclass
class SegmentUnit:
    department: Department
    kind: str
    name: str
    head_role: str
    headcount: int
    region_key: str | None
    children: list[SegmentUnit] = field(default_factory=list)
    departments: list[DeptUnit] = field(default_factory=list)


@dataclass
class OrgBlueprint:
    executive_office: DeptUnit
    corporate: list[DeptUnit]
    segments: list[SegmentUnit]
    departments: list[Department]

    def total_headcount(self) -> int:
        def seg_total(seg: SegmentUnit) -> int:
            return seg.headcount

        return (
            self.executive_office.headcount
            + sum(u.headcount for u in self.corporate)
            + sum(seg_total(s) for s in self.segments)
        )


class DepartmentGenerator:
    def __init__(
        self, config: OrgGraphConfig, catalog: DepartmentCatalog, industries: IndustryCatalog
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._industries = industries
        self._workforce = config.dataset.workforce

    def generate(
        self,
        company_index: int,
        company: Company,
        context: CompanyContext,
        industry: str,
        archetype: ArchetypeConfig,
        rng: Rng,
    ) -> OrgBlueprint:
        builder = _BlueprintBuilder(self, company_index, company, context, industry, archetype, rng)
        return builder.build()


class _BlueprintBuilder:
    def __init__(
        self,
        gen: DepartmentGenerator,
        company_index: int,
        company: Company,
        context: CompanyContext,
        industry: str,
        archetype: ArchetypeConfig,
        rng: Rng,
    ) -> None:
        self.cfg = gen._config
        self.catalog = gen._catalog
        self.industries = gen._industries
        self.workforce = gen._workforce
        self.company_index = company_index
        self.company = company
        self.context = context
        self.industry = industry
        self.archetype = archetype
        self.rng = rng
        self.departments: list[Department] = []

    def _department(
        self, name: str, dept_type: DepartmentType, parent: Department | None, key: str
    ) -> Department:
        dept = Department(
            department_id=department_id(self.company_index, len(self.departments) + 1),
            company_id=self.company.company_id,
            department_name=name,
            department_type=dept_type,
            parent_department_id=parent.department_id if parent else None,
            department_key=key,
        )
        self.departments.append(dept)
        return dept

    def _allocate(self, total: int, weights: dict[str, float], minimum: int) -> dict[str, int]:
        keys = sorted(weights, key=lambda k: -weights[k])
        while keys:
            parts = largest_remainder(total, [weights[k] for k in keys])
            if min(parts) >= minimum or len(keys) == 1:
                return dict(zip(keys, parts, strict=True))
            keys.pop()
        return {}

    def _select_departments(self) -> dict[str, float]:
        candidates = self.industries.candidate_departments(self.industry, self.company.employee_count)
        jitter = self.workforce.department_weight_jitter
        selected = {
            key: weight * self.rng.lognormal_factor(jitter)
            for key, (probability, weight) in candidates.items()
            if self.rng.bernoulli(probability)
        }
        if len(selected) < 2:
            for key, (_, weight) in sorted(candidates.items(), key=lambda kv: -kv[1][1])[:2]:
                selected.setdefault(key, weight)
        return selected

    def _functional_unit(self, key: str, headcount: int, parent: Department | None) -> DeptUnit:
        dept_cfg = self.catalog.top_level(key)
        dept = self._department(dept_cfg.name, DepartmentType.FUNCTION, parent, key)
        unit = DeptUnit(department=dept, key=key, headcount=headcount, direct_headcount=headcount - 1)
        subs = [s for s in dept_cfg.subdepartments if s.min_parent_headcount <= headcount]
        if len(subs) < 2:
            return unit
        direct = round((headcount - 1) * self.workforce.department_direct_share)
        sub_total = headcount - 1 - direct
        alloc = self._allocate(
            sub_total, {s.key: s.weight for s in subs}, self.workforce.min_subdepartment_headcount
        )
        if len(alloc) < 2:
            return unit
        by_key = {s.key: s for s in subs}
        for sub_key in [s.key for s in subs if s.key in alloc]:
            sub_dept = self._department(by_key[sub_key].name, DepartmentType.SUB_FUNCTION, dept, sub_key)
            size = alloc[sub_key]
            unit.subunits.append(
                DeptUnit(department=sub_dept, key=sub_key, headcount=size, direct_headcount=size - 1)
            )
        unit.direct_headcount = headcount - 1 - sum(u.headcount for u in unit.subunits)
        return unit

    def _build_segments(
        self,
        layers: list[SegmentLayerConfig],
        depth: int,
        total: int,
        dept_weights: dict[str, float],
        parent: Department | None,
        parent_name: str | None,
    ) -> list[SegmentUnit]:
        layer = layers[depth]
        max_segments = len(self.context.region_keys) if layer.kind == "region" else 99
        count = segment_count(layer, total, max_segments, self.rng)
        if count < 2:
            return []
        names = segment_names(self.cfg, layer, self.industry, self.context, count, parent_name, self.rng)
        sizes = split_with_minimum(
            self.rng, total, len(names), min(layer.min_headcount, total // len(names)), 3.0
        )
        segments: list[SegmentUnit] = []
        for (name, region_key), size in zip(names, sizes, strict=True):
            seg_dept = self._department(name, _SEGMENT_TYPES[layer.kind], parent, layer.kind)
            seg = SegmentUnit(
                department=seg_dept,
                kind=layer.kind,
                name=name,
                head_role=layer.head_role,
                headcount=size,
                region_key=region_key,
            )
            body = size - 1
            if depth + 1 < len(layers):
                seg.children = self._build_segments(layers, depth + 1, body, dept_weights, seg_dept, name)
            if not seg.children:
                alloc = self._allocate(body, dept_weights, self.workforce.min_department_headcount)
                seg.departments = [self._functional_unit(k, n, seg_dept) for k, n in alloc.items()]
            segments.append(seg)
        return segments

    def build(self) -> OrgBlueprint:
        n = self.company.employee_count
        support = min(
            self.workforce.executive_support_max,
            max(1, n // self.workforce.executive_support_per_employees),
        )
        eo_cfg = self.catalog.top_level("executive_office")
        eo_dept = self._department(eo_cfg.name, DepartmentType.EXECUTIVE, None, "executive_office")
        executive_office = DeptUnit(
            department=eo_dept,
            key="executive_office",
            headcount=1 + support,
            direct_headcount=support,
        )

        weights = self._select_departments()
        alloc = self._allocate(
            n - executive_office.headcount, weights, self.workforce.min_department_headcount
        )
        weights = {k: weights[k] for k in alloc}

        corporate_keys = list(alloc)
        segments: list[SegmentUnit] = []
        layers = list(self.archetype.segmentation)
        if layers:
            tags = set(layers[0].department_tags)
            seg_keys = [k for k in alloc if tags & set(self.catalog.top_level(k).tags)]
            pool = sum(alloc[k] for k in seg_keys)
            if seg_keys and pool >= 2 * layers[0].min_headcount:
                segments = self._build_segments(
                    layers, 0, pool, {k: weights[k] for k in seg_keys}, None, None
                )
                if segments:
                    corporate_keys = [k for k in alloc if k not in seg_keys]
        corporate = [self._functional_unit(k, alloc[k], None) for k in corporate_keys]
        blueprint = OrgBlueprint(
            executive_office=executive_office,
            corporate=corporate,
            segments=segments,
            departments=list(self.departments),
        )
        if blueprint.total_headcount() != n:
            raise RuntimeError(
                f"{self.company.company_id}: blueprint headcount {blueprint.total_headcount()} != {n}"
            )
        return blueprint
