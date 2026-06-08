"""LangSmith tracing helper.

Wraps the LLM call path with LangSmith's ``@traceable`` ONLY when ``langsmith``
is installed AND ``LANGSMITH_API_KEY`` is set. The import is guarded so the
decorator degrades to a transparent no-op offline / in CI, never crashing when
the package or key is absent.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from typing import TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def _langsmith_enabled() -> bool:
    if not os.getenv("LANGSMITH_API_KEY"):
        return False
    try:
        import langsmith  # noqa: F401
    except ImportError:
        return False
    return True


def traceable_if_enabled(*, name: str) -> Callable[[F], F]:
    """Return LangSmith's ``@traceable(name=...)`` if enabled, else a no-op.

    The decorated function's signature is preserved either way, so call sites are
    identical whether or not tracing is active.
    """

    def decorator(func: F) -> F:
        if not _langsmith_enabled():
            return func
        from langsmith import traceable

        wrapped: F = traceable(name=name)(func)  # type: ignore[assignment]
        return wrapped

    return decorator
