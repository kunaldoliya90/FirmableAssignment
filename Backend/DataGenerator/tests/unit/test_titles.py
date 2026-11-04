# Title taxonomy expansion and variant lookup
from __future__ import annotations

from collections import Counter

from orggraph_dataset.taxonomy import TitleTaxonomy, normalize_title


def test_canonical_titles_are_unique(taxonomy: TitleTaxonomy) -> None:
    titles = [normalize_title(t.canonical_title) for t in taxonomy.all_titles()]
    assert len(titles) == len(set(titles))
    assert len(titles) > 400


def test_every_title_has_required_fields(taxonomy: TitleTaxonomy) -> None:
    for entry in taxonomy.all_titles():
        assert entry.job_family
        assert entry.seniority_level
        assert entry.title_variants[0] == entry.canonical_title
        assert entry.industry_compatibility
        assert entry.is_management == (
            entry.seniority_level not in {"intern", "junior", "ic", "senior_ic", "staff", "principal"}
        )


def test_variants_map_back_to_canonical(taxonomy: TitleTaxonomy) -> None:
    ambiguous = set(taxonomy.ambiguous_variants())
    checked = 0
    for entry in taxonomy.all_titles():
        for variant in (*entry.title_variants, *entry.legacy_titles):
            if normalize_title(variant) in ambiguous:
                continue
            assert taxonomy.resolve_variant(variant) == entry.canonical_title, variant
            checked += 1
    assert checked > 2000


def test_known_examples(taxonomy: TitleTaxonomy) -> None:
    assert taxonomy.resolve_variant("Sr. SWE") == "Senior Software Engineer"
    assert taxonomy.resolve_variant("Engg Mgr") == "Engineering Manager"
    assert taxonomy.resolve_variant("sr mgr - engg") == "Senior Engineering Manager"
    assert taxonomy.resolve_variant("VP - Engineering") == "VP Engineering"
    assert taxonomy.resolve_variant("CTO") == "Chief Technology Officer"
    assert taxonomy.resolve_variant("not a real title at all") is None


def test_shared_variants_are_reported_as_ambiguous(taxonomy: TitleTaxonomy) -> None:
    ambiguous = taxonomy.ambiguous_variants()
    assert set(ambiguous["cmo"]) == {"Chief Marketing Officer", "Chief Medical Officer"}
    assert taxonomy.resolve_variant("CMO") is None


def test_progression_and_fallbacks(taxonomy: TitleTaxonomy) -> None:
    ladder = [
        taxonomy.title_for("software_engineering", level).canonical_title
        for level in (
            "ic",
            "senior_ic",
            "staff",
            "principal",
            "manager",
            "senior_manager",
            "director",
            "senior_director",
            "vp",
            "svp",
        )
    ]
    assert ladder == [
        "Software Engineer",
        "Senior Software Engineer",
        "Staff Software Engineer",
        "Principal Engineer",
        "Engineering Manager",
        "Senior Engineering Manager",
        "Director of Engineering",
        "Senior Director of Engineering",
        "VP Engineering",
        "SVP Engineering",
    ]
    assert taxonomy.title_for("hr", "principal").seniority_level == "staff"
    assert taxonomy.executive_title("cto").canonical_title == "Chief Technology Officer"


def test_previous_and_adjacent_titles(taxonomy: TitleTaxonomy) -> None:
    senior = taxonomy.title_for("software_engineering", "senior_ic")
    previous = taxonomy.previous_title(senior)
    assert previous is not None and previous.canonical_title == "Software Engineer"
    manager = taxonomy.title_for("software_engineering", "manager")
    assert taxonomy.previous_title(manager).canonical_title == "Senior Software Engineer"  # type: ignore[union-attr]
    adjacent = taxonomy.adjacent_title(manager, 1)
    assert adjacent is not None and adjacent.seniority_level == "senior_manager"
    assert taxonomy.previous_title(taxonomy.executive_title("ceo")) is None


def test_department_compatibility(taxonomy: TitleTaxonomy) -> None:
    entry = taxonomy.title_for("software_engineering", "ic")
    assert "engineering" in entry.department_compatibility
    seniority = Counter(t.seniority_level for t in taxonomy.all_titles())
    assert set(seniority) == set(taxonomy.seniority_levels())
