"""Structlog logging configuration.

Mirrors loop-scribe's ``utils/logging/log_config.py``:

- Dev (``APP_ENV=local``): colored console output.
- Cloud (``APP_ENV=dev|prod``): JSON output suitable for log aggregation.
- Log level controlled by ``LOG_LEVEL`` env var (default ``INFO``).

Reads directly from ``os.environ`` because this runs at import time, before
Dynaconf settings are available.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

_configured = False


def setup_logging() -> None:
    """Configure structlog wrapping stdlib logging (idempotent)."""
    global _configured  # noqa: PLW0603
    if _configured:
        return
    _configured = True

    env = os.environ.get("APP_ENV", "local")
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    is_local = env == "local"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_local:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))
