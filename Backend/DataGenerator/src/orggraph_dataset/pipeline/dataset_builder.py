# Builds every record for one company, from departments through observations
from __future__ import annotations

from collections import Counter

from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.generators.archetype_generator import archetype_spec
from orggraph_dataset.generators.company_generator import CompanyPlan, generate_company
from orggraph_dataset.generators.department_generator import DepartmentGenerator
from orggraph_dataset.generators.employee_generator import EmployeeGenerator
from orggraph_dataset.generators.hierarchy_generator import HierarchyGenerator
from orggraph_dataset.generators.observation_generator import ObservationGenerator
from orggraph_dataset.generators.position_generator import generate_positions
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.taxonomy import IndustryCatalog, TitleTaxonomy
from orggraph_dataset.utils.random_utils import Rng


class CompanyBuilder:
    def __init__(self, config: OrgGraphConfig, taxonomy: TitleTaxonomy | None = None) -> None:
        self.config = config
        self.taxonomy = taxonomy or TitleTaxonomy(config)
        self.industries = IndustryCatalog(config)
        self.departments = DepartmentGenerator(config, self.taxonomy.departments, self.industries)
        self.hierarchy = HierarchyGenerator(config, self.taxonomy)
        self.employees = EmployeeGenerator(config)
        self._observation_generators: dict[str, ObservationGenerator] = {}

    def _observations(self, profile: str) -> ObservationGenerator:
        if profile not in self._observation_generators:
            self._observation_generators[profile] = ObservationGenerator(self.config, self.taxonomy, profile)
        return self._observation_generators[profile]

    def build(self, plan: CompanyPlan) -> CompanyRecords:
        rng = Rng(plan.generation_seed)
        company, context = generate_company(plan, self.config, rng.child("metadata"))
        archetype = archetype_spec(self.config, plan.archetype)

        blueprint = self.departments.generate(
            plan.index, company, context, plan.industry, archetype, rng.child("departments")
        )
        tree = self.hierarchy.generate(
            blueprint, plan.employee_count, plan.industry, archetype, rng.child("hierarchy")
        )
        positions, titles = generate_positions(plan.index, company.company_id, tree, self.taxonomy)

        profile = self.config.profile(plan.noise_profile)
        departed_rng = rng.child("departed")
        departed_count = int(departed_rng.np.binomial(plan.employee_count, profile.departed_employee_rate))
        workforce = self.employees.generate(
            plan.index,
            company.company_id,
            context,
            tree,
            positions,
            titles,
            departed_count,
            rng.child("people"),
            departed_rng,
        )
        observations, labels, noise_counts = self._observations(plan.noise_profile).generate(
            plan.index,
            company.company_id,
            tree,
            titles,
            workforce,
            blueprint.departments,
            context,
            rng.child("observations"),
        )

        observed_employees = [e.to_observed() for e in workforce.employees]
        observed_employees += [d.to_observed() for d in workforce.departed]
        rng.child("export_order").shuffle(observed_employees)

        children = tree.children_counts()
        managers = [c for c in children if c > 0]
        stats = {
            "max_depth": tree.max_depth,
            "manager_count": len(managers),
            "max_span": max(managers) if managers else 0,
            "mean_span": sum(managers) / len(managers) if managers else 0.0,
            "segment_count": len(blueprint.segments),
            "department_count": len(blueprint.departments),
            "seniority_counts": dict(Counter(p.seniority_level.value for p in positions)),
            "noise_operation_counts": noise_counts,
        }
        return CompanyRecords(
            company=company,
            departments=blueprint.departments,
            positions=positions,
            employees=workforce.employees,
            reporting_edges=workforce.reporting_edges,
            secondary_edges=workforce.secondary_edges,
            departed_employees=workforce.departed,
            observed_employees=observed_employees,
            observations=observations,
            observation_labels=labels,
            stats=stats,
        )
