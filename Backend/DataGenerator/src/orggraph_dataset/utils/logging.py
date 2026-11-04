# Logging setup
from __future__ import annotations

import logging
import os
import sys

_LOGGER_NAME = "orggraph_dataset"


def configure_logging(level: str | None = None) -> None:
    resolved = (level or os.environ.get("ORGGRAPH_LOG_LEVEL") or "INFO").upper()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(resolved)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME if name is None else f"{_LOGGER_NAME}.{name}")
