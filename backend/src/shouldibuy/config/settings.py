"""Application settings via Dynaconf.

Mirrors loop-scribe's ``config/settings.py``: ``get_settings()`` loads a base
``application.toml`` merged with an environment-specific overlay selected by the
``APP_ENV`` environment variable (default ``local``). Any ``APP_*`` environment
variable overrides a setting (``envvar_prefix="APP"``).
"""

from __future__ import annotations

import os
from pathlib import Path

from dynaconf import Dynaconf

_CONFIG_DIR = Path(__file__).parent / "properties"


def get_settings() -> Dynaconf:
    """Create a Dynaconf settings instance based on ``APP_ENV``."""
    env = os.getenv("APP_ENV", "local")
    return Dynaconf(
        envvar_prefix="APP",
        settings_files=[
            str(_CONFIG_DIR / "application.toml"),
            str(_CONFIG_DIR / f"application-{env}.toml"),
        ],
        environments=False,
        merge_enabled=True,
        load_dotenv=True,
    )
