# Assign synthetic people to positions and derive ground-truth reporting edges
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Any

from faker import Faker

from orggraph_dataset.config import CityConfig, OrgGraphConfig
from orggraph_dataset.constants import IC_LEVELS
from orggraph_dataset.generators.company_generator import CompanyContext
from orggraph_dataset.generators.hierarchy_generator import OrgTree
from orggraph_dataset.schemas import (
    DepartedEmployee,
    Employee,
    EmploymentType,
    Position,
    RelationshipType,
    ReportingEdge,
    SecondaryEdge,
    SeniorityLevel,
)
from orggraph_dataset.taxonomy import CanonicalTitle
from orggraph_dataset.utils.ids import employee_id
from orggraph_dataset.utils.random_utils import Rng, derive_seed


@dataclass(frozen=True)
class EmployeeLocation:
    city: CityConfig
    remote: bool

    @property
    def display(self) -> str:
        if self.remote:
            return f"Remote - {self.city.country}"
        return f"{self.city.name}, {self.city.country}"


@lru_cache(maxsize=32)
def _faker(locale: str) -> Any:
    return Faker(locale)


class NameFactory:
    def __init__(self, config: OrgGraphConfig, seed: int) -> None:
        self._config = config
        self._seed = seed
        self._seeded: set[str] = set()

    def name(self, region: str, rng: Rng) -> tuple[str, str]:
        locale = rng.choice(self._config.locations.regions[region].faker_locales)
        fake = _faker(locale)
        if locale not in self._seeded:
            fake.seed_instance(derive_seed(self._seed, "faker", locale))
            self._seeded.add(locale)
        first = str(fake.first_name()).strip()
        last = str(fake.last_name()).strip()
        return first or "Alex", last or "Morgan"


@dataclass
class WorkforceResult:
    employees: list[Employee]
    locations: list[EmployeeLocation]
    reporting_edges: list[ReportingEdge]
    secondary_edges: list[SecondaryEdge]
    departed: list[DepartedEmployee]


class EmployeeGenerator:
    def __init__(self, config: OrgGraphConfig) -> None:
        self._config = config
        self._workforce = config.dataset.workforce

    def _location(self, region: str | None, context: CompanyContext, rng: Rng) -> EmployeeLocation:
        offices = list(context.offices)
        if region is not None:
            offices = [c for c in offices if c.region == region] or offices
            city = rng.choice(offices)
        elif rng.bernoulli(self._workforce.hq_location_probability):
            city = context.headquarters
        else:
            city = rng.choice(offices)
        return EmployeeLocation(city=city, remote=rng.bernoulli(self._workforce.remote_probability))

    def _employment_type(self, seniority: str, rng: Rng) -> EmploymentType:
        if seniority == "intern":
            return EmploymentType.INTERN
        if seniority not in IC_LEVELS:
            return EmploymentType.FULL_TIME
        return EmploymentType(rng.weighted_key(self._workforce.employment_type_mix))

    def generate(
        self,
        company_index: int,
        company_id: str,
        context: CompanyContext,
        tree: OrgTree,
        positions: list[Position],
        titles: list[CanonicalTitle],
        departed_count: int,
        people_rng: Rng,
        departed_rng: Rng,
    ) -> WorkforceResult:
        n = len(tree.nodes)
        names = NameFactory(self._config, people_rng.seed)
        id_order = people_rng.child("ids", departed_count).permutation(n + departed_count)
        ids = [employee_id(company_index, i + 1) for i in id_order]

        employees: list[Employee] = []
        locations: list[EmployeeLocation] = []
        for node, position, title in zip(tree.nodes, positions, titles, strict=True):
            location = self._location(node.region_key, context, people_rng)
            first, last = names.name(location.city.region, people_rng)
            locations.append(location)
            employees.append(
                Employee(
                    employee_id=ids[node.index],
                    company_id=company_id,
                    full_name=f"{first} {last}",
                    first_name=first,
                    last_name=last,
                    canonical_title=title.canonical_title,
                    canonical_department=node.department.department_name,
                    job_family=title.job_family,
                    seniority_level=SeniorityLevel(title.seniority_level),
                    location=location.display,
                    employment_type=self._employment_type(title.seniority_level, people_rng),
                    position_id=position.position_id,
                )
            )

        edges = [
            ReportingEdge(
                company_id=company_id,
                employee_id=ids[node.index],
                manager_employee_id=ids[node.parent] if node.parent is not None else None,
                relationship_type=RelationshipType.PRIMARY
                if node.parent is not None
                else RelationshipType.ROOT,
                hierarchy_depth=node.depth,
            )
            for node in tree.nodes
        ]
        secondary = [
            SecondaryEdge(company_id=company_id, employee_id=ids[member], manager_employee_id=ids[manager])
            for member, manager in tree.secondary
        ]

        departed: list[DepartedEmployee] = []
        reference = self._config.dataset.reference_date
        departed_names = NameFactory(self._config, departed_rng.seed)
        for j in range(departed_count):
            node = tree.nodes[departed_rng.randint(1, n - 1)] if n > 1 else tree.nodes[0]
            title = titles[node.index]
            location = self._location(node.region_key, context, departed_rng)
            first, last = departed_names.name(location.city.region, departed_rng)
            departed.append(
                DepartedEmployee(
                    employee_id=ids[n + j],
                    company_id=company_id,
                    full_name=f"{first} {last}",
                    first_name=first,
                    last_name=last,
                    last_canonical_title=title.canonical_title,
                    last_canonical_department=node.department.department_name,
                    job_family=title.job_family,
                    seniority_level=SeniorityLevel(title.seniority_level),
                    employment_type=self._employment_type(title.seniority_level, departed_rng),
                    departed_on=reference - timedelta(days=departed_rng.randint(30, 720)),
                )
            )
        return WorkforceResult(employees, locations, edges, secondary, departed)
