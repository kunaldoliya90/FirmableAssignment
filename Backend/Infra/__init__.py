# Shared infrastructure: settings and logging
from __future__ import annotations

import os
from functools import lru_cache

from Infra.Common.BaseSettings import CommonSettings
from Infra.Local.LocalSettings import LocalSettings
from Infra.Production.ProductionSettings import ProductionSettings

_SETTINGS_CLASSES: dict[str, type[CommonSettings]] = {
    "local": LocalSettings,
    "test": LocalSettings,
    "production": ProductionSettings,
}


@lru_cache(maxsize=1)
def get_settings() -> CommonSettings:
    env = os.environ.get("FIRMABLE_ENV", "local").lower()
    try:
        settings_cls = _SETTINGS_CLASSES[env]
    except KeyError as exc:
        raise ValueError(f"FIRMABLE_ENV must be one of {sorted(_SETTINGS_CLASSES)}, got {env!r}") from exc
    if env == "test":
        return settings_cls(environment="test")
    return settings_cls()


__all__ = ["CommonSettings", "LocalSettings", "ProductionSettings", "get_settings"]
