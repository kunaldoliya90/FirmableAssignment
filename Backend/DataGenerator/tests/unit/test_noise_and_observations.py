# Noise operations and multi-source observation generation
from __future__ import annotations

from collections import Counter

import pytest
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import NULLABLE_OBSERVATION_FIELDS, SOURCES
from orggraph_dataset.generators.noise_generator import NoiseContext, NoiseEngine
from orggraph_dataset.pipeline.dataset_builder import CompanyBuilder
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.taxonomy import TitleTaxonomy
from orggraph_dataset.utils.random_utils import Rng

from tests.conftest import make_plan


@pytest.fixture(scope="module")
def engine(config: OrgGraphConfig) -> NoiseEngine:
    return NoiseEngine(config.noise, config.profile("high_noise"))


@pytest.fixture(scope="module")
def context(config: OrgGraphConfig) -> NoiseContext:
    city = next(c for c in config.locations.cities if c.name == "New York")
    return NoiseContext(
        department_name="Engineering",
        department_abbreviations=("Eng", "Engg"),
        department_aliases=("R&D",),
        parent_department_name="Technology",
        segment_name="Consumer",
        region=config.locations.regions["north_america"],
        city=city,
    )


@pytest.mark.parametrize(
    "op",
    [
        "variant",
        "abbreviation",
        "typo",
        "punctuation",
        "capitalization",
        "seniority_removal",
        "truncation",
        "department_suffix",
        "regional_suffix",
        "business_unit_suffix",
        "generic_replacement",
        "legacy_title",
    ],
)
def test_each_title_operation_changes_the_title(
    engine: NoiseEngine, context: NoiseContext, taxonomy: TitleTaxonomy, op: str
) -> None:
    entry = taxonomy.title_for("software_engineering", "senior_ic")
    title = entry.canonical_title
    changed = engine._title_ops[op](title, entry, context, Rng(4))
    assert changed and changed != title


def test_abbreviation_examples(engine: NoiseEngine, context: NoiseContext, taxonomy: TitleTaxonomy) -> None:
    entry = taxonomy.title_for("software_engineering", "senior_manager")
    outputs = {engine._abbreviation(entry.canonical_title, entry, context, Rng(i)) for i in range(30)}
    assert any(o and ("Sr" in o or "Mgr" in o or "Eng" in o) for o in outputs)


def test_seniority_removal(engine: NoiseEngine) -> None:
    assert engine.remove_seniority("Senior Software Engineer") == "Software Engineer"
    assert engine.remove_seniority("Sr. Data Analyst") == "Data Analyst"
    assert engine.remove_seniority("Software Engineer II") == "Software Engineer"
    assert engine.remove_seniority("Accountant") is None


def test_department_and_location_noise(engine: NoiseEngine, context: NoiseContext) -> None:
    departments = {engine.corrupt_department(context, Rng(i)).value for i in range(60)}
    assert len(departments) > 4 and "Technology" in departments
    locations = {engine.corrupt_location(context, Rng(i)).value for i in range(60)}
    assert {"NYC", "North America"} & locations
    assert len(locations) > 4


def test_clean_profile_produces_canonical_observations(builder: CompanyBuilder) -> None:
    records = builder.build(make_plan(index=21, noise_profile="clean", employee_count=300))
    canonical = {e.employee_id: e for e in records.employees}
    assert not records.departed_employees
    for obs, label in zip(records.observations, records.observation_labels, strict=True):
        assert label.noise_applied == []
        emp = canonical[obs.employee_id]
        assert obs.observed_title == emp.canonical_title
        assert obs.observed_department == emp.canonical_department
        assert obs.observed_location == emp.location
        assert set(obs.missing_fields) <= {"observed_job_family"}


def test_noise_profiles_scale_noise(builder: CompanyBuilder) -> None:
    def noisy_share(profile: str) -> float:
        records = builder.build(make_plan(index=22, noise_profile=profile, employee_count=600))
        noisy = sum(1 for lbl in records.observation_labels if lbl.noise_applied)
        return noisy / len(records.observation_labels)

    low, medium, high = noisy_share("low_noise"), noisy_share("medium_noise"), noisy_share("high_noise")
    assert low < medium < high


def test_structure_is_identical_across_noise_profiles(builder: CompanyBuilder) -> None:
    a = builder.build(make_plan(index=23, noise_profile="low_noise"))
    b = builder.build(make_plan(index=23, noise_profile="high_noise"))
    assert a.positions == b.positions
    assert a.departments == b.departments


def test_observation_invariants(tech_company: CompanyRecords) -> None:
    observed = Counter(o.employee_id for o in tech_company.observations)
    assert all(observed[e.employee_id] >= 1 for e in tech_company.employees)
    assert len(tech_company.observations) > len(tech_company.employees) * 1.5
    labels = {lbl.observation_id: lbl for lbl in tech_company.observation_labels}
    current = {e.employee_id for e in tech_company.employees}
    for obs in tech_company.observations:
        assert obs.employee_id and obs.company_id == tech_company.company.company_id
        nulls = {f for f in NULLABLE_OBSERVATION_FIELDS if getattr(obs, f) is None}
        assert set(obs.missing_fields) == nulls
        label = labels[obs.observation_id]
        assert obs.source is None or obs.source == label.true_source
        assert label.true_source.value in SOURCES
        if obs.historical_manager_id is not None:
            assert obs.historical_manager_id in current
            assert label.true_source.value == "historical_snapshot"
    sources = Counter(lbl.true_source.value for lbl in tech_company.observation_labels)
    assert set(sources) == set(SOURCES)


def test_noise_types_present(tech_company: CompanyRecords) -> None:
    ops = Counter(op for lbl in tech_company.observation_labels for op in lbl.noise_applied)
    for expected in (
        "title_variant",
        "title_abbreviation",
        "missing_department",
        "missing_location",
        "stale_title",
        "location_city_alias",
        "department_alias",
        "source_conflict_title",
    ):
        assert ops[expected] > 0, expected


def test_historical_manager_flag_matches_truth(tech_company: CompanyRecords) -> None:
    manager = {e.employee_id: e.manager_employee_id for e in tech_company.reporting_edges}
    labels = {lbl.observation_id: lbl for lbl in tech_company.observation_labels}
    for obs in tech_company.observations:
        if obs.historical_manager_id:
            is_current = manager.get(obs.employee_id) == obs.historical_manager_id
            assert labels[obs.observation_id].historical_manager_is_current == is_current
