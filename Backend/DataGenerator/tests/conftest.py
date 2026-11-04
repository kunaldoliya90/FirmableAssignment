# Shared fixtures: config, taxonomy, a company builder and a small dataset
from __future__ import annotations

from pathlib import Path

import pytest
from orggraph_dataset.config import OrgGraphConfig, load_config
from orggraph_dataset.generators.company_generator import CompanyPlan
from orggraph_dataset.pipeline.dataset_builder import CompanyBuilder
from orggraph_dataset.pipeline.orchestrator import GenerationResult, GenerationSettings, run_generation
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.taxonomy import TitleTaxonomy
from orggraph_dataset.utils.random_utils import derive_seed

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="session")
def config() -> OrgGraphConfig:
    return load_config(CONFIG_DIR)


@pytest.fixture(scope="session")
def taxonomy(config: OrgGraphConfig) -> TitleTaxonomy:
    return TitleTaxonomy(config)


@pytest.fixture(scope="session")
def builder(config: OrgGraphConfig, taxonomy: TitleTaxonomy) -> CompanyBuilder:
    return CompanyBuilder(config, taxonomy)


def make_plan(
    index: int = 1,
    industry: str = "technology",
    employee_count: int = 400,
    archetype: str = "functional",
    noise_profile: str = "medium_noise",
    split: str = "train",
    seed: int = 42,
    size_segment: str | None = None,
) -> CompanyPlan:
    if size_segment is None:
        size_segment = next(
            seg
            for seg, (lo, hi) in {
                "small": (100, 249),
                "mid_small": (250, 499),
                "mid_market": (500, 999),
                "large": (1000, 4999),
                "enterprise": (5000, 20000),
            }.items()
            if lo <= employee_count <= hi
        )
    return CompanyPlan(
        index=index,
        company_id=f"company_{index:05d}",
        company_name=f"Testco {index}",
        industry=industry,
        size_segment=size_segment,
        employee_count=employee_count,
        archetype=archetype,
        split=split,
        noise_profile=noise_profile,
        generation_seed=derive_seed(seed, "company", index),
    )


@pytest.fixture(scope="session")
def tech_company(builder: CompanyBuilder) -> CompanyRecords:
    return builder.build(make_plan(employee_count=420))


@pytest.fixture(scope="session")
def small_dataset(tmp_path_factory: pytest.TempPathFactory, config: OrgGraphConfig) -> GenerationResult:
    out = tmp_path_factory.mktemp("small_dataset")
    settings = GenerationSettings.from_config(
        config, companies=16, target_employees=1600, seed=11, output_dir=out, batch_size=4
    )
    return run_generation(config, settings)
