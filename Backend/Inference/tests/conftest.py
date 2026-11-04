# Shared fixtures: vocabulary, engine and clean and noisy generated datasets
from __future__ import annotations

from pathlib import Path

import pytest
from orggraph_dataset.config import OrgGraphConfig, load_config
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation
from orggraph_inference.normalization import Vocabulary, load_vocabulary
from orggraph_inference.pipeline import InferenceEngine


@pytest.fixture(scope="session")
def dataset_config() -> OrgGraphConfig:
    return load_config()


@pytest.fixture(scope="session")
def vocabulary() -> Vocabulary:
    return load_vocabulary()


@pytest.fixture(scope="session")
def engine(vocabulary: Vocabulary) -> InferenceEngine:
    return InferenceEngine(vocabulary=vocabulary)


def _generate(root: Path, config: OrgGraphConfig, profile: str, seed: int) -> Path:
    settings = GenerationSettings.from_config(
        config,
        companies=8,
        target_employees=1600,
        seed=seed,
        noise_profile=profile,
        challenge_noise_profile=profile,
        output_dir=root,
        validate_after_export=False,
    )
    run_generation(config, settings)
    return root


@pytest.fixture(scope="session")
def noisy_dataset(tmp_path_factory: pytest.TempPathFactory, dataset_config: OrgGraphConfig) -> Path:
    return _generate(tmp_path_factory.mktemp("noisy"), dataset_config, "medium_noise", 21)


@pytest.fixture(scope="session")
def clean_dataset(tmp_path_factory: pytest.TempPathFactory, dataset_config: OrgGraphConfig) -> Path:
    return _generate(tmp_path_factory.mktemp("clean"), dataset_config, "clean", 21)
