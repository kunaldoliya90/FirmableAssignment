# Process-wide logging configuration (plain text locally, JSON lines in production)
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from Infra.Common.BaseSettings import CommonSettings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: CommonSettings) -> None:
    handler = logging.StreamHandler(sys.stderr)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    generator_logger = logging.getLogger("orggraph_dataset")
    generator_logger.handlers = []
    generator_logger.propagate = True
    generator_logger.setLevel(settings.log_level)
