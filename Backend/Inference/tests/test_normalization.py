# Title, department and location normalization
from __future__ import annotations

import pytest
from orggraph_inference.normalization import (
    DepartmentNormalizer,
    LocationNormalizer,
    TitleNormalizer,
    Vocabulary,
    clean,
)


@pytest.fixture(scope="module")
def titles(vocabulary: Vocabulary) -> TitleNormalizer:
    return TitleNormalizer(vocabulary)


def test_clean() -> None:
    assert clean("  Sr. SWE - Platform/Infra (EMEA) ") == "sr swe platform infra emea"
    assert clean("Zürich") == "zurich"


@pytest.mark.parametrize(
    ("raw", "canonical", "seniority"),
    [
        ("Sr. SWE", "Senior Software Engineer", "senior_ic"),
        ("Engg Mgr", "Engineering Manager", "manager"),
        ("sr mgr - engg", "Senior Engineering Manager", "senior_manager"),
        ("VP - Engineering", "VP Engineering", "vp"),
        ("Chief Exec Officer", "Chief Executive Officer", "c_level"),
        ("SENIOR SOFTWARE ENGINEER", "Senior Software Engineer", "senior_ic"),
        ("Senior Netwokr Engineer", "Senior Network Engineer", "senior_ic"),
        ("Data Engineering M", "Data Engineering Manager", "manager"),
        ("Financial Anlst", "Financial Analyst", "ic"),
        ("Director, Engineering (EMEA)", "Director of Engineering", "director"),
        ("Programmer Analyst", "Software Engineer", "ic"),
    ],
)
def test_title_resolution(titles: TitleNormalizer, raw: str, canonical: str, seniority: str) -> None:
    result = titles.interpret(raw)
    assert result.canonical_title == canonical
    assert result.seniority == seniority


def test_generic_and_ambiguous_titles(titles: TitleNormalizer) -> None:
    generic = titles.interpret("Head of Department")
    assert generic.generic and generic.canonical_title is None and generic.seniority == "director"
    shared = titles.interpret("CMO")
    assert shared.canonical_title is None and shared.seniority == "c_level"
    assert titles.interpret("Sales Manager - Consumer").suffix == "consumer"


def test_keyword_fallback(titles: TitleNormalizer) -> None:
    result = titles.interpret("Global Head of Something Unusual")
    assert result.seniority == "director" and result.method == "keyword"


def test_departments(vocabulary: Vocabulary) -> None:
    norm = DepartmentNormalizer(vocabulary)
    allowed = frozenset(vocabulary.config.industries.industries["technology"].departments)
    assert norm.interpret("D&A", allowed).key == "data_analytics"
    backend = norm.interpret("Backend Eng", allowed)
    assert backend.key == "backend_engineering" and backend.top_key == "engineering"
    prefixed = norm.interpret("Consumer - Engineering", allowed)
    assert prefixed.key == "engineering" and prefixed.segment == "consumer"
    segment_only = norm.interpret("Consumer BU", allowed)
    assert segment_only.key is None and segment_only.segment == "consumer"
    plant = frozenset(vocabulary.config.industries.industries["manufacturing"].departments)
    assert norm.interpret("Engineering", plant).key == "industrial_engineering"


def test_locations(vocabulary: Vocabulary) -> None:
    norm = LocationNormalizer(vocabulary)
    assert norm.interpret("NYC").city == "New York"
    assert norm.interpret("SIN, SG").region == "apac"
    remote = norm.interpret("Remote - Japan")
    assert remote.remote and remote.region == "apac"
    assert norm.interpret("EMEA").region == "emea"
