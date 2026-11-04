# Production settings
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from Infra.Common.BaseSettings import CommonSettings


class ProductionSettings(CommonSettings):
    environment: Literal["local", "production", "test"] = "production"
    log_json: bool = True
    docs_enabled: bool = False
    allow_dataset_generation: bool = False
    datasets_dir: Path = Path("/data/datasets")
    artifacts_dir: Path = Path("/data/artifacts")
    cors_origins: list[str] = Field(default_factory=list)
    reload: bool = False

    @model_validator(mode="after")
    def _no_wildcard_cors(self) -> ProductionSettings:
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origins are not allowed in production")
        return self
