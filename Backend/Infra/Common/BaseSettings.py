# Settings shared by every environment
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class InferenceSettings(BaseModel):
    # None keeps the engine's tuned threshold (learned_weights.json); set it only to override
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_candidates: int = Field(default=25, ge=1)
    company_cache_size: int = Field(default=64, ge=1)


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FIRMABLE_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "FirmableAssignment API"
    environment: Literal["local", "production", "test"] = "local"
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True

    log_level: str = "INFO"
    log_json: bool = False

    backend_root: Path = BACKEND_ROOT
    datasets_dir: Path = BACKEND_ROOT / "DataGenerator" / "datasets"
    generator_config_dir: Path = BACKEND_ROOT / "DataGenerator" / "config"
    artifacts_dir: Path = BACKEND_ROOT / "DataGenerator" / "datasets" / "_artifacts"
    # read-only artifacts baked into the image; copied into artifacts_dir at startup when missing there
    seed_artifacts_dir: Path | None = None
    default_dataset: str = "FirmableAssignmentDataset"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # e.g. ^https://firmable-[a-z0-9-]+\.vercel\.app$ for Vercel preview deployments
    cors_origin_regex: str | None = None
    frontend_url: str = "http://localhost:3000"

    inference: InferenceSettings = Field(default_factory=InferenceSettings)

    allow_dataset_generation: bool = True
    max_generation_companies: int = Field(default=500, ge=1)
    job_workers: int = Field(default=2, ge=1)

    @field_validator("api_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return value

    @field_validator("log_level")
    @classmethod
    def _level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level {value!r}")
        return upper
