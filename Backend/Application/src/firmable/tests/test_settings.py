# Settings selection and production guards
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import Infra
from firmable.main import create_app
from Infra.Common.BaseSettings import CommonSettings
from Infra.Local.LocalSettings import LocalSettings
from Infra.Production.ProductionSettings import ProductionSettings


def test_settings_factory_selects_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    Infra.get_settings.cache_clear()
    monkeypatch.setenv("FIRMABLE_ENV", "production")
    monkeypatch.setenv("FIRMABLE_CORS_ORIGINS", '["https://app.example.com"]')
    settings = Infra.get_settings()
    assert isinstance(settings, ProductionSettings)
    assert settings.log_json and not settings.docs_enabled and not settings.allow_dataset_generation
    assert Infra.get_settings() is settings
    Infra.get_settings.cache_clear()
    monkeypatch.setenv("FIRMABLE_ENV", "local")
    assert isinstance(Infra.get_settings(), LocalSettings)
    Infra.get_settings.cache_clear()
    monkeypatch.setenv("FIRMABLE_ENV", "staging")
    with pytest.raises(ValueError, match="FIRMABLE_ENV"):
        Infra.get_settings()
    Infra.get_settings.cache_clear()


def test_nested_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRMABLE_INFERENCE__CONFIDENCE_THRESHOLD", "0.7")
    monkeypatch.setenv("FIRMABLE_API_PREFIX", "api/v2/")
    settings = CommonSettings()
    assert settings.inference.confidence_threshold == 0.7
    assert settings.api_prefix == "/api/v2"


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        ProductionSettings(cors_origins=["*"])


def test_production_disables_generation(datasets_dir: Path) -> None:
    settings = ProductionSettings(datasets_dir=datasets_dir, artifacts_dir=datasets_dir / "_artifacts")
    client = TestClient(create_app(settings))
    response = client.post("/api/v1/datasets", json={"dataset_id": "nope", "companies": 2})
    assert response.status_code == 403
    assert client.get("/docs").status_code == 404


def test_production_rejects_unanchored_cors_regex() -> None:
    with pytest.raises(ValueError, match="arbitrary origins"):
        ProductionSettings(cors_origin_regex=r"https://.*")
    settings = ProductionSettings(cors_origin_regex=r"^https://firmable-[a-z0-9-]+\.vercel\.app$")
    assert settings.cors_origin_regex


def test_cors_regex_allows_preview_origins(datasets_dir: Path) -> None:
    settings = ProductionSettings(
        datasets_dir=datasets_dir,
        artifacts_dir=datasets_dir / "_artifacts",
        cors_origins=["https://firmable.vercel.app"],
        cors_origin_regex=r"^https://firmable-[a-z0-9-]+\.vercel\.app$",
    )
    client = TestClient(create_app(settings))

    def allowed(origin: str) -> str | None:
        response = client.get("/api/v1/health", headers={"Origin": origin})
        value: str | None = response.headers.get("access-control-allow-origin")
        return value

    assert allowed("https://firmable.vercel.app") == "https://firmable.vercel.app"
    assert allowed("https://firmable-git-main-team.vercel.app") == "https://firmable-git-main-team.vercel.app"
    assert allowed("https://evil.vercel.app") is None


def test_unset_threshold_keeps_engine_default(settings: LocalSettings) -> None:
    from orggraph_inference.config import InferenceConfig

    from firmable.services import ServiceContainer

    assert settings.inference.confidence_threshold is None
    services = ServiceContainer.build(settings)
    assert services.inference.config.confidence_threshold == InferenceConfig().confidence_threshold
    services.jobs.shutdown()
