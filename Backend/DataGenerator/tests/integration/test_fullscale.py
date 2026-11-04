# Full 500-company minimum dataset, run with -m fullscale
from __future__ import annotations

from pathlib import Path

import pytest
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation


@pytest.mark.fullscale
def test_minimum_dataset(config: OrgGraphConfig, tmp_path: Path) -> None:
    settings = GenerationSettings.from_config(
        config,
        companies=500,
        min_employees_per_company=100,
        target_employees=50_000,
        seed=42,
        noise_profile="medium_noise",
        output_dir=tmp_path / "full",
    )
    result = run_generation(config, settings)
    manifest = result.manifest
    assert manifest.company_count == 500
    assert manifest.employee_count >= 50_000
    assert manifest.reporting_edge_count == manifest.employee_count - 500
    assert result.validation is not None and result.validation.ok
    assert result.validation.issue_counts.get("leakage.forbidden_field", 0) == 0
    assert min(p.employee_count for p in result.plan.companies) >= 100
    assert len(manifest.industry_distribution) == 19
    assert len(manifest.company_size_distribution) == 5
    assert len(manifest.archetype_distribution) == 7
