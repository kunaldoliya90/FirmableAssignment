# Employee profile construction
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from orggraph_dataset.constants import SENIORITY_RANK
from orggraph_dataset.schemas import EmployeeObservation, EmploymentStatus

from orggraph_inference.config import InferenceConfig
from orggraph_inference.data import ObservedCompanyData
from orggraph_inference.normalization import (
    DepartmentNormalizer,
    LocationNormalizer,
    TitleNormalizer,
    Vocabulary,
    clean,
)

CEO_RANK = SENIORITY_RANK["c_level"] + 1.0
STATUS_SOURCES = {"hr_export", "internal_directory"}
CURRENT_SOURCES = {"hr_export", "internal_directory", "company_directory"}
ABSENCE_ONLY_DEPARTED = 0.7


@dataclass
class EmployeeProfile:
    employee_id: str
    company_id: str
    full_name: str
    employment_type: str
    observation_count: int
    sources: list[str]
    title: str | None = None
    canonical_title: str | None = None
    job_family: str | None = None
    seniority: str | None = None
    rank: float = float(SENIORITY_RANK["ic"])
    executive_role: str | None = None
    seniority_confidence: float = 0.0
    family_confidence: float = 0.0
    generic_title: bool = False
    department_key: str | None = None
    department_top_key: str | None = None
    department_name: str | None = None
    department_confidence: float = 0.0
    segment: str | None = None
    region: str | None = None
    city: str | None = None
    departed: bool = False
    departed_confidence: float = 0.0
    historical_managers: dict[str, float] = field(default_factory=dict)

    @property
    def is_ceo(self) -> bool:
        return self.executive_role == "ceo"

    @property
    def is_manager_level(self) -> bool:
        return self.rank >= SENIORITY_RANK["manager"]


def _vote(votes: dict[str, float]) -> tuple[str | None, float]:
    if not votes:
        return None, 0.0
    winner = max(votes, key=lambda k: (votes[k], k))
    total = sum(votes.values())
    return winner, votes[winner] / total if total else 0.0


def _votes() -> defaultdict[str, float]:
    return defaultdict(float)


@dataclass
class _Votes:
    seniority: defaultdict[str, float] = field(default_factory=_votes)
    family: defaultdict[str, float] = field(default_factory=_votes)
    canonical: defaultdict[str, float] = field(default_factory=_votes)
    exec_roles: defaultdict[str, float] = field(default_factory=_votes)
    titles: defaultdict[str, float] = field(default_factory=_votes)
    departments: defaultdict[str, float] = field(default_factory=_votes)
    dept_names: defaultdict[str, float] = field(default_factory=_votes)
    segments: defaultdict[str, float] = field(default_factory=_votes)
    regions: defaultdict[str, float] = field(default_factory=_votes)
    cities: defaultdict[str, float] = field(default_factory=_votes)
    managers: defaultdict[str, float] = field(default_factory=_votes)
    generic_weight: float = 0.0
    specific_weight: float = 0.0
    former: float = 0.0
    active: float = 0.0
    has_current_source: bool = False


class ProfileBuilder:
    def __init__(self, vocabulary: Vocabulary, config: InferenceConfig) -> None:
        self.vocab = vocabulary
        self.config = config
        self.titles = TitleNormalizer(vocabulary, config.fuzzy_title_threshold)
        self.departments = DepartmentNormalizer(vocabulary, config.fuzzy_department_threshold)
        self.locations = LocationNormalizer(vocabulary)
        self._region_names = {
            clean(name): key
            for key, region in vocabulary.config.locations.regions.items()
            for name in (region.name, *region.aliases)
        }

    def allowed_departments(self, industry_name: str) -> frozenset[str]:
        key = self.vocab.industry_keys.get(industry_name)
        if key is None:
            return frozenset(self.vocab.config.departments.departments)
        return frozenset({*self.vocab.config.industries.industries[key].departments, "executive_office"})

    def _weight(self, obs: EmployeeObservation, reference: datetime | None) -> float:
        reliability = self.config.source_reliability
        weight = reliability.get(obs.source.value if obs.source else "unknown", reliability["unknown"])
        if obs.observed_at is not None and reference is not None:
            age_days = max((reference - obs.observed_at).total_seconds() / 86400, 0.0)
            weight *= math.pow(0.5, age_days / self.config.recency_half_life_days)
        else:
            weight *= 0.5
        return weight

    def build(self, data: ObservedCompanyData) -> dict[str, EmployeeProfile]:
        allowed = self.allowed_departments(data.company.industry)
        reference = max((o.observed_at for o in data.observations if o.observed_at), default=None)
        by_employee: dict[str, list[EmployeeObservation]] = defaultdict(list)
        for obs in data.observations:
            by_employee[obs.employee_id].append(obs)

        profiles: dict[str, EmployeeProfile] = {}
        for emp in data.employees:
            observations = by_employee.get(emp.employee_id, [])
            profile = EmployeeProfile(
                employee_id=emp.employee_id,
                company_id=emp.company_id,
                full_name=emp.full_name,
                employment_type=emp.employment_type.value,
                observation_count=len(observations),
                sources=sorted({o.source.value for o in observations if o.source}),
            )
            self._fill(profile, observations, allowed, reference)
            profiles[emp.employee_id] = profile
        self._infer_missing_functions(profiles)
        return profiles

    def _fill(
        self,
        profile: EmployeeProfile,
        observations: list[EmployeeObservation],
        allowed: frozenset[str],
        reference: datetime | None,
    ) -> None:
        votes = _Votes()
        for obs in observations:
            w = self._weight(obs, reference)
            self._tally_status(votes, obs)
            if obs.observed_title:
                self._tally_title(votes, obs.observed_title, w, allowed)
            if obs.observed_department:
                self._tally_department(votes, obs.observed_department, w, allowed)
            if obs.observed_location:
                self._tally_location(votes, obs.observed_location, w)
            if obs.historical_manager_id:
                votes.managers[obs.historical_manager_id] += 1.0
        self._apply_votes(profile, votes)

    def _tally_status(self, votes: _Votes, obs: EmployeeObservation) -> None:
        source = obs.source.value if obs.source else None
        if source in CURRENT_SOURCES:
            votes.has_current_source = True
        status_weight = 1.0 if source in STATUS_SOURCES else 0.3
        if obs.employment_status is EmploymentStatus.FORMER:
            votes.former += status_weight
        elif (
            obs.employment_status in (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
            and source != "historical_snapshot"
        ):
            votes.active += status_weight

    def _tally_title(self, votes: _Votes, title: str, w: float, allowed: frozenset[str]) -> None:
        interp = self.titles.interpret(title)
        tw = w * max(interp.score, 0.05)
        votes.titles[title] += tw
        if interp.seniority:
            votes.seniority[interp.seniority] += tw
        if interp.job_family:
            votes.family[interp.job_family] += tw
        if interp.canonical_title:
            votes.canonical[interp.canonical_title] += tw
        if interp.executive_role:
            votes.exec_roles[interp.executive_role] += tw
        if interp.generic:
            votes.generic_weight += w
        else:
            votes.specific_weight += w
        if interp.suffix:
            self._suffix_hint(
                interp.suffix, allowed, w * 0.5, votes.departments, votes.segments, votes.regions
            )

    def _tally_department(self, votes: _Votes, name: str, w: float, allowed: frozenset[str]) -> None:
        dept = self.departments.interpret(name, allowed)
        if dept.key:
            votes.departments[dept.key] += w * dept.score
            votes.dept_names[name] += w
        if dept.segment:
            votes.segments[dept.segment] += w * 0.8

    def _tally_location(self, votes: _Votes, location: str, w: float) -> None:
        loc = self.locations.interpret(location)
        if loc.region:
            votes.regions[loc.region] += w
        if loc.city:
            votes.cities[loc.city] += w

    def _apply_votes(self, profile: EmployeeProfile, votes: _Votes) -> None:
        profile.title = _vote(votes.titles)[0]
        profile.seniority, profile.seniority_confidence = _vote(votes.seniority)
        profile.job_family, profile.family_confidence = _vote(votes.family)
        profile.canonical_title = _vote(votes.canonical)[0]
        role, role_conf = _vote(votes.exec_roles)
        profile.executive_role = role if role_conf >= 0.5 else None
        profile.generic_title = votes.generic_weight > votes.specific_weight
        if profile.seniority:
            profile.rank = float(SENIORITY_RANK[profile.seniority])
        if profile.is_ceo:
            profile.rank = CEO_RANK
        key, conf = _vote(votes.departments)
        if key:
            profile.department_key = key
            profile.department_top_key = self.departments.top_key(key)
            profile.department_confidence = conf
            profile.department_name = _vote(votes.dept_names)[0]
        profile.segment = _vote(votes.segments)[0]
        profile.region = _vote(votes.regions)[0]
        profile.city = _vote(votes.cities)[0]
        total = sum(votes.managers.values())
        profile.historical_managers = {m: v / total for m, v in votes.managers.items()} if total else {}

        status_total = votes.former + votes.active
        departed_score = votes.former / status_total if status_total else 0.0
        if not votes.has_current_source:
            departed_score = max(departed_score, ABSENCE_ONLY_DEPARTED)
        profile.departed_confidence = round(departed_score, 3)
        profile.departed = departed_score >= self.config.departed_threshold

    def _suffix_hint(
        self,
        suffix: str,
        allowed: frozenset[str],
        weight: float,
        departments: dict[str, float],
        segments: dict[str, float],
        regions: dict[str, float],
    ) -> None:
        if suffix in self._region_names:
            regions[self._region_names[suffix]] += weight
            return
        loc = self.locations.interpret(suffix)
        if loc.city or loc.region:
            if loc.region:
                regions[loc.region] += weight
            return
        dept = self.departments.interpret(suffix, allowed)
        if dept.key and dept.score >= 0.75:
            departments[dept.key] += weight * dept.score
        elif dept.segment:
            segments[dept.segment] += weight

    def _infer_missing_functions(self, profiles: dict[str, EmployeeProfile]) -> None:
        family_departments: dict[str, Counter[str]] = defaultdict(Counter)
        for p in profiles.values():
            if p.job_family and p.department_key:
                family_departments[p.job_family][p.department_key] += 1
        for p in profiles.values():
            if p.department_key is None and p.job_family in family_departments:
                key, count = family_departments[p.job_family].most_common(1)[0]
                total = sum(family_departments[p.job_family].values())
                p.department_key = key
                p.department_top_key = self.departments.top_key(key)
                p.department_confidence = 0.5 * count / total
