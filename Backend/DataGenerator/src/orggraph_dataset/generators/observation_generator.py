# Multi-source employee observations
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from orggraph_dataset.config import OrgGraphConfig, SourceConfig
from orggraph_dataset.constants import NULLABLE_OBSERVATION_FIELDS, SENIORITY_RANK
from orggraph_dataset.generators.company_generator import CompanyContext
from orggraph_dataset.generators.employee_generator import WorkforceResult
from orggraph_dataset.generators.hierarchy_generator import OrgNode, OrgTree
from orggraph_dataset.generators.noise_generator import NoiseContext, NoiseEngine
from orggraph_dataset.schemas import (
    Department,
    DepartmentType,
    EmployeeObservation,
    EmploymentStatus,
    ObservationLabel,
    Source,
)
from orggraph_dataset.taxonomy import CanonicalTitle, TitleTaxonomy
from orggraph_dataset.utils.ids import observation_id
from orggraph_dataset.utils.random_utils import Rng

_SEGMENT_SUFFIXES = {
    DepartmentType.BUSINESS_UNIT: ("BU", "Business Unit", "Group"),
    DepartmentType.DIVISION: ("Division", "Div", "Unit"),
    DepartmentType.REGION: ("Region", "Regional Office", "Market"),
    DepartmentType.PRODUCT_LINE: ("Product Line", "Product Group", "Products"),
}


@dataclass(frozen=True)
class _Subject:
    employee_id: str
    title: CanonicalTitle
    previous_title: CanonicalTitle | None
    department_name: str
    previous_department: str | None
    context: NoiseContext
    family_key: str
    employment_type: str
    manager_id: str | None
    alternative_manager_id: str | None
    departed: bool

    @property
    def has_history(self) -> bool:
        return self.previous_title is not None or self.previous_department is not None


@dataclass
class _Observation:
    title_entry: CanonicalTitle
    department: str | None
    source: str | None
    title: str | None = None
    location: str | None = None
    family: str | None = None
    observed_at: datetime | None = None
    stale: bool = False
    ops: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    subject: _Subject
    source: str
    record: dict[str, object]
    label: dict[str, object]


class ObservationGenerator:
    def __init__(self, config: OrgGraphConfig, taxonomy: TitleTaxonomy, profile_name: str) -> None:
        self.cfg = config
        self.tax = taxonomy
        self.profile_name = profile_name
        self.profile = config.profile(profile_name)
        self.engine = NoiseEngine(config.noise, self.profile)
        self.sources = config.sources.sources
        self.reference = datetime.combine(config.dataset.reference_date, time(), tzinfo=UTC)

    def _department_context(
        self, dept: Department, by_id: dict[str, Department]
    ) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
        parent = by_id.get(dept.parent_department_id) if dept.parent_department_id else None
        if dept.department_key in self.tax.departments:
            entry = self.tax.departments.entry(dept.department_key)
            return entry.abbreviations, entry.aliases, parent.department_name if parent else None
        suffixes = _SEGMENT_SUFFIXES.get(dept.department_type, ())
        aliases = tuple(f"{dept.department_name} {s}" for s in suffixes)
        return (), aliases, parent.department_name if parent else None

    def _subjects(
        self,
        tree: OrgTree,
        titles: list[CanonicalTitle],
        workforce: WorkforceResult,
        departments: list[Department],
        context: CompanyContext,
        rng: Rng,
    ) -> list[_Subject]:
        by_id = {d.department_id: d for d in departments}
        functional = [
            d.department_name
            for d in departments
            if d.department_type in (DepartmentType.FUNCTION, DepartmentType.SUB_FUNCTION)
        ] or [d.department_name for d in departments]
        managers = [n.index for n in tree.nodes if SENIORITY_RANK[n.seniority] >= SENIORITY_RANK["manager"]]
        regions = self.cfg.locations.regions
        ids = [e.employee_id for e in workforce.employees]
        subjects: list[_Subject] = []
        for node, title, employee, location in zip(
            tree.nodes, titles, workforce.employees, workforce.locations, strict=True
        ):
            abbreviations, aliases, parent_name = self._department_context(node.department, by_id)
            promoted = rng.bernoulli(self.profile.promotion_rate)
            transferred = rng.bernoulli(self.profile.transfer_rate)
            previous_title = self.tax.previous_title(title) if promoted else None
            previous_department = None
            if transferred:
                others = [name for name in functional if name != node.department.department_name]
                previous_department = rng.choice(others) if others else None
            manager_id = ids[node.parent] if node.parent is not None else None
            alternative = self._alternative_manager(node, managers, ids, rng)
            subjects.append(
                _Subject(
                    employee_id=employee.employee_id,
                    title=title,
                    previous_title=previous_title,
                    department_name=node.department.department_name,
                    previous_department=previous_department,
                    context=NoiseContext(
                        department_name=node.department.department_name,
                        department_abbreviations=abbreviations,
                        department_aliases=aliases,
                        parent_department_name=parent_name,
                        segment_name=node.segment_names[-1] if node.segment_names else None,
                        region=regions[location.city.region],
                        city=location.city,
                        remote=location.remote,
                    ),
                    family_key=title.job_family,
                    employment_type=employee.employment_type.value,
                    manager_id=manager_id,
                    alternative_manager_id=alternative,
                    departed=False,
                )
            )
        for person in workforce.departed:
            title = self.tax.entry(person.last_canonical_title)
            subjects.append(
                _Subject(
                    employee_id=person.employee_id,
                    title=title,
                    previous_title=None,
                    department_name=person.last_canonical_department,
                    previous_department=None,
                    context=NoiseContext(
                        department_name=person.last_canonical_department,
                        region=regions[context.headquarters.region],
                        city=context.headquarters,
                    ),
                    family_key=title.job_family,
                    employment_type=person.employment_type.value,
                    manager_id=None,
                    alternative_manager_id=ids[rng.choice(managers)] if managers else None,
                    departed=True,
                )
            )
        return subjects

    @staticmethod
    def _alternative_manager(node: OrgNode, managers: list[int], ids: list[str], rng: Rng) -> str | None:
        if node.parent is None or len(managers) < 3:
            return None
        for _ in range(6):
            candidate = rng.choice(managers)
            if candidate not in (node.index, node.parent):
                return ids[candidate]
        return None

    def _sources_for(self, subject: _Subject, rng: Rng) -> list[str]:
        if subject.departed:
            coverage = self.cfg.sources.departed_source_coverage
            chosen = [s for s, p in coverage.items() if rng.bernoulli(p)]
            return chosen or ["historical_snapshot"]
        multiplier = self.profile.source_coverage_multiplier
        chosen = []
        for key, src in self.sources.items():
            base = src.coverage_by_employment_type.get(subject.employment_type, src.coverage)
            if rng.bernoulli(min(1.0, base * multiplier)):
                chosen.append(key)
        return chosen or [self.cfg.sources.fallback_source]

    def _observe(self, subject: _Subject, source_key: str, rng: Rng) -> _Draft:
        src: SourceConfig = self.sources[source_key]
        obs = _Observation(title_entry=subject.title, department=subject.department_name, source=source_key)
        self._apply_staleness(obs, subject, src, rng)
        obs.title = obs.title_entry.canonical_title
        self._apply_source_conflict(obs, subject, src, rng)
        self._apply_title_noise(obs, subject, src, rng)
        self._apply_department_noise(obs, subject, src, rng)
        self._apply_location_noise(obs, subject, src, rng)
        self._apply_job_family(obs, subject, src, rng)
        self._apply_missing_fields(obs, src, rng)
        self._apply_timestamp(obs, src, rng)
        status = self._status(subject, src, source_key, rng)
        historical_manager, historical_is_current = self._historical_manager(obs, subject, src, rng)

        record: dict[str, object] = {
            "employee_id": subject.employee_id,
            "observed_title": obs.title,
            "observed_department": obs.department,
            "observed_job_family": obs.family,
            "observed_location": obs.location,
            "source": obs.source,
            "observed_at": obs.observed_at,
            "employment_status": status,
            "historical_manager_id": historical_manager,
        }
        record["missing_fields"] = [f for f in NULLABLE_OBSERVATION_FIELDS if record[f] is None]
        label: dict[str, object] = {
            "employee_id": subject.employee_id,
            "canonical_title": subject.title.canonical_title,
            "canonical_department": subject.department_name,
            "true_source": source_key,
            "noise_applied": obs.ops,
            "is_stale": obs.stale,
            "is_departed_employee": subject.departed,
            "historical_manager_is_current": historical_is_current,
        }
        return _Draft(subject, source_key, record, label)

    def _apply_staleness(self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng) -> None:
        if not subject.has_history:
            return
        if not (
            src.always_historical
            or rng.bernoulli(self.profile.stale_observation_probability * src.stale_multiplier)
        ):
            return
        obs.stale = True
        if subject.previous_title is not None:
            obs.title_entry = subject.previous_title
            obs.ops.append("stale_title")
        if subject.previous_department is not None:
            obs.department = subject.previous_department
            obs.ops.append("previous_department")

    def _apply_source_conflict(
        self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng
    ) -> None:
        if not rng.bernoulli(self.profile.source_conflict_probability * src.conflict_multiplier):
            return
        ctx = subject.context
        if rng.bernoulli(0.5):
            adjacent = self.tax.adjacent_title(obs.title_entry, rng.choice([-1, 1]))
            if adjacent is not None:
                obs.title_entry = adjacent
                obs.title = adjacent.canonical_title
                obs.ops.append("source_conflict_title")
        elif ctx.parent_department_name or ctx.segment_name:
            obs.department = ctx.parent_department_name or ctx.segment_name
            obs.ops.append("source_conflict_department")

    def _apply_title_noise(self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng) -> None:
        p = self.profile
        if obs.title and rng.bernoulli(p.title_corruption_probability * src.title_noise_multiplier):
            result = self.engine.corrupt_title(obs.title, obs.title_entry, subject.context, rng)
            obs.title = result.value
            obs.ops += result.operations
        if not (obs.title and rng.bernoulli(p.ambiguity_probability)):
            return
        if SENIORITY_RANK[obs.title_entry.seniority_level] >= SENIORITY_RANK["manager"]:
            obs.title = self.engine.generic_leadership_title(obs.title_entry.seniority_level, rng)
            obs.ops.append("ambiguity_generic_leadership")
            if obs.department and rng.bernoulli(0.5):
                obs.department = None
                obs.ops.append("ambiguity_department_dropped")
        else:
            stripped = self.engine.remove_seniority(obs.title)
            if stripped:
                obs.title = stripped
                obs.ops.append("ambiguity_seniority_dropped")

    def _apply_department_noise(
        self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng
    ) -> None:
        if (
            obs.department
            and obs.department == subject.department_name
            and rng.bernoulli(
                self.profile.department_inconsistency_probability * src.department_noise_multiplier
            )
        ):
            result = self.engine.corrupt_department(subject.context, rng)
            obs.department = result.value
            obs.ops += result.operations

    def _apply_location_noise(
        self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng
    ) -> None:
        obs.location = self.engine.base_location(subject.context)
        if obs.location and rng.bernoulli(
            self.profile.location_noise_probability * src.location_noise_multiplier
        ):
            result = self.engine.corrupt_location(subject.context, rng)
            obs.location = result.value
            obs.ops += result.operations

    def _apply_job_family(self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng) -> None:
        if not src.includes_job_family:
            return
        obs.family = self.tax.families.display_name(subject.family_key)
        if rng.bernoulli(self.profile.department_inconsistency_probability * 0.5):
            aliases = self.tax.families.aliases(subject.family_key)
            if aliases:
                obs.family = rng.choice(aliases)
                obs.ops.append("job_family_alias")

    def _apply_missing_fields(self, obs: _Observation, src: SourceConfig, rng: Rng) -> None:
        p = self.profile
        if obs.title and rng.bernoulli(p.missing_title_probability * src.missing_title_multiplier):
            obs.title = None
            obs.ops.append("missing_title")
        if obs.department and rng.bernoulli(
            p.missing_department_probability * src.missing_department_multiplier
        ):
            obs.department = None
            obs.ops.append("missing_department")
        if obs.location and rng.bernoulli(p.missing_location_probability * src.missing_location_multiplier):
            obs.location = None
            obs.ops.append("missing_location")
        if obs.family and rng.bernoulli(p.missing_job_family_probability * src.missing_job_family_multiplier):
            obs.family = None
            obs.ops.append("missing_job_family")
        if rng.bernoulli(p.missing_source_probability):
            obs.source = None
            obs.ops.append("missing_source")

    def _apply_timestamp(self, obs: _Observation, src: SourceConfig, rng: Rng) -> None:
        low, high = src.age_days
        age = timedelta(days=rng.randint(low, high), seconds=rng.randint(0, 86399))
        obs.observed_at = self.reference - age
        if rng.bernoulli(self.profile.missing_timestamp_probability):
            obs.observed_at = None
            obs.ops.append("missing_timestamp")

    def _historical_manager(
        self, obs: _Observation, subject: _Subject, src: SourceConfig, rng: Rng
    ) -> tuple[str | None, bool | None]:
        if not (
            src.provides_historical_manager and rng.bernoulli(self.profile.historical_manager_probability)
        ):
            return None, None
        manager: str | None = None
        is_current: bool | None = None
        if subject.departed or (subject.has_history and obs.stale):
            manager = subject.alternative_manager_id
            is_current = False if manager else None
        elif subject.manager_id is not None:
            manager = subject.manager_id
            is_current = True
        if manager:
            obs.ops.append("historical_manager")
        return manager, is_current

    def _status(self, subject: _Subject, src: SourceConfig, source_key: str, rng: Rng) -> EmploymentStatus:
        if subject.departed:
            if source_key == "historical_snapshot":
                return EmploymentStatus.ACTIVE
            if src.reports_employment_status:
                return EmploymentStatus.FORMER
            return rng.choice([EmploymentStatus.FORMER, EmploymentStatus.UNKNOWN, EmploymentStatus.ACTIVE])
        if src.reports_employment_status:
            if rng.bernoulli(self.cfg.dataset.workforce.on_leave_probability):
                return EmploymentStatus.ON_LEAVE
            return EmploymentStatus.ACTIVE
        if rng.bernoulli(src.status_unknown_probability):
            return EmploymentStatus.UNKNOWN
        return EmploymentStatus.ACTIVE

    def generate(
        self,
        company_index: int,
        company_id: str,
        tree: OrgTree,
        titles: list[CanonicalTitle],
        workforce: WorkforceResult,
        departments: list[Department],
        context: CompanyContext,
        rng: Rng,
    ) -> tuple[list[EmployeeObservation], list[ObservationLabel], dict[str, int]]:
        subject_rng = rng.child("subjects")
        subjects = self._subjects(tree, titles, workforce, departments, context, subject_rng)
        drafts: list[_Draft] = []
        for subject in subjects:
            for source_key in self._sources_for(subject, rng):
                drafts.append(self._observe(subject, source_key, rng))

        rng.child("order").shuffle(drafts)
        observations: list[EmployeeObservation] = []
        labels: list[ObservationLabel] = []
        op_counts: Counter[str] = Counter()
        for i, draft in enumerate(drafts, start=1):
            obs_id = observation_id(company_index, i)
            source = draft.record["source"]
            noise_applied = draft.label["noise_applied"]
            assert isinstance(noise_applied, list)
            observations.append(
                EmployeeObservation.model_validate(
                    {
                        **draft.record,
                        "observation_id": obs_id,
                        "company_id": company_id,
                        "source": Source(str(source)) if source else None,
                    }
                )
            )
            labels.append(
                ObservationLabel.model_validate(
                    {**draft.label, "observation_id": obs_id, "company_id": company_id}
                )
            )
            op_counts.update(str(op) for op in noise_applied)
        return observations, labels, dict(op_counts)
