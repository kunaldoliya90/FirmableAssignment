# Local development settings: verbose logs, local paths, permissive CORS for the Next.js dev server
from __future__ import annotations

from typing import Literal

from pydantic import Field

from Infra.Common.BaseSettings import CommonSettings


class LocalSettings(CommonSettings):
    environment: Literal["local", "production", "test"] = "local"
    log_level: str = "INFO"
    log_json: bool = False
    docs_enabled: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    allow_dataset_generation: bool = True
    reload: bool = True
