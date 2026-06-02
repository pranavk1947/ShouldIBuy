"""Shared test fixtures / path setup.

Ensures ``src`` is importable when running pytest without an editable install,
and resets structlog config between tests (mirrors loop-scribe's conftest).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402
import structlog  # noqa: E402

import shouldibuy.utils.logging.log_config as log_config_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Reset structlog + stdlib logging state between tests."""
    yield
    structlog.reset_defaults()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    log_config_module._configured = False
