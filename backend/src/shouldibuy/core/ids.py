"""Identifier generation helpers."""

from __future__ import annotations

import secrets

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _short_id(length: int = 12) -> str:
    """Return a URL-safe lowercase alphanumeric id."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_analysis_id() -> str:
    """Generate an analysis id, e.g. ``an_8x3k1p0qz9ab``."""
    return f"an_{_short_id()}"


def new_trace_id() -> str:
    """Generate a trace id for correlating logs/events."""
    return f"trace_{_short_id(16)}"
