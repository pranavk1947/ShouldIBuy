"""Tracing helpers.

A light, dependency-free ``traced`` decorator placeholder so the fallback chain
(and other modules) can import it without pulling in OpenTelemetry yet.

TODO(M3): replace this no-op with real OTEL span creation, mirroring
loop-scribe's ``utils/observability/tracing.py`` (start_as_current_span,
record_exception, set_status).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any


def traced(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap an async function in a (currently no-op) tracing span.

    The ``span_name`` is accepted and ignored for now so call sites already use
    the final API. When OTEL is wired in M3, only this function changes.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # TODO(M3): start_as_current_span(span_name); record exceptions.
            return await func(*args, **kwargs)

        return wrapper

    return decorator
