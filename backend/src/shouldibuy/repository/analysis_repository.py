"""Analysis repository + per-analysis SSE event bus (was ``core/store.py``).

M0 ships an in-memory, async-safe implementation behind ``AnalysisRepository``
(a ``Protocol``) so a Postgres/Redis-backed repository can replace it in M1
without touching callers. Idempotency-by-key and the late-subscriber history
replay behavior are preserved exactly.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from typing import Protocol
from typing import runtime_checkable

import structlog

from shouldibuy.model.analysis import Analysis

logger = structlog.get_logger(__name__)

# Sentinel pushed onto an analysis queue to signal "no more events".
STREAM_END = object()


@runtime_checkable
class AnalysisRepository(Protocol):
    """Storage + event-bus interface. M1 swaps this for a Postgres/Redis impl."""

    async def create(self, analysis: Analysis) -> None: ...

    async def get(self, analysis_id: str) -> Optional[Analysis]: ...

    async def update(self, analysis: Analysis) -> None: ...

    async def publish(self, analysis_id: str, event: dict) -> None:
        """Push a serialized SSE event to all subscribers and history."""
        ...

    async def finish(self, analysis_id: str) -> None:
        """Signal that no more events will be published for this analysis."""
        ...

    async def subscribe(self, analysis_id: str) -> asyncio.Queue[object]:
        """Return a fresh queue pre-loaded with buffered history."""
        ...

    async def unsubscribe(
        self, analysis_id: str, queue: asyncio.Queue[object]
    ) -> None: ...

    # Idempotency support (process-local for M0).
    async def get_by_idempotency_key(self, key: str) -> Optional[str]: ...

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None: ...


class InMemoryAnalysisRepository:
    """Async-safe in-memory repository guarded by a single lock.

    Doubles as the per-analysis event bus: each connected SSE client gets its
    own ``asyncio.Queue``, and every published event is also buffered into
    history so a late subscriber can replay what already happened.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[str, Analysis] = {}
        self._idempotency: dict[str, str] = {}
        self._subscribers: dict[str, list[asyncio.Queue[object]]] = {}
        self._history: dict[str, list[object]] = {}
        self._finished: set[str] = set()

    async def create(self, analysis: Analysis) -> None:
        async with self._lock:
            self._items[analysis.analysis_id] = analysis
            self._subscribers.setdefault(analysis.analysis_id, [])
            self._history.setdefault(analysis.analysis_id, [])

    async def get(self, analysis_id: str) -> Optional[Analysis]:
        async with self._lock:
            return self._items.get(analysis_id)

    async def update(self, analysis: Analysis) -> None:
        async with self._lock:
            self._items[analysis.analysis_id] = analysis

    async def publish(self, analysis_id: str, event: dict) -> None:
        async with self._lock:
            if analysis_id not in self._items:
                return
            self._history.setdefault(analysis_id, []).append(event)
            subscribers = list(self._subscribers.get(analysis_id, []))
        for queue in subscribers:
            queue.put_nowait(event)

    async def finish(self, analysis_id: str) -> None:
        async with self._lock:
            if analysis_id not in self._items:
                return
            self._finished.add(analysis_id)
            subscribers = list(self._subscribers.get(analysis_id, []))
        for queue in subscribers:
            queue.put_nowait(STREAM_END)

    async def subscribe(self, analysis_id: str) -> asyncio.Queue[object]:
        queue: asyncio.Queue[object] = asyncio.Queue()
        async with self._lock:
            if analysis_id not in self._items:
                # Unknown analysis: caller will close immediately.
                queue.put_nowait(STREAM_END)
                return queue
            # Replay history so a late subscriber sees prior events.
            for event in self._history.get(analysis_id, []):
                queue.put_nowait(event)
            if analysis_id in self._finished:
                queue.put_nowait(STREAM_END)
            else:
                self._subscribers.setdefault(analysis_id, []).append(queue)
        return queue

    async def unsubscribe(
        self, analysis_id: str, queue: asyncio.Queue[object]
    ) -> None:
        async with self._lock:
            subs = self._subscribers.get(analysis_id)
            if subs is not None and queue in subs:
                subs.remove(queue)

    async def get_by_idempotency_key(self, key: str) -> Optional[str]:
        async with self._lock:
            return self._idempotency.get(key)

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None:
        async with self._lock:
            self._idempotency[key] = analysis_id
