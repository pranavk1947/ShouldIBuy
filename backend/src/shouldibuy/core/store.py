"""Analysis store and per-analysis SSE event bus.

M0 ships an in-memory, async-safe implementation behind ``AnalysisStore`` (a
``Protocol``) so a Postgres-backed store can replace it in M1 without touching
callers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from shouldibuy.domain.models import (
    AnalysisSnapshot,
    AnalysisStatus,
    ConditionDTO,
    ListingDTO,
    MarketVerdictDTO,
    VerdictDTO,
)

# Sentinel pushed onto an analysis queue to signal "no more events".
STREAM_END = object()


@dataclass
class Analysis:
    """Mutable record holding the current state of one analysis."""

    analysis_id: str
    trace_id: str
    status: AnalysisStatus = "queued"
    listing: Optional[ListingDTO] = None
    market_verdict: Optional[MarketVerdictDTO] = None
    condition: Optional[ConditionDTO] = None
    verdict: Optional[VerdictDTO] = None
    # Subscriber queues for SSE. Each connected client gets its own queue.
    _subscribers: list[asyncio.Queue[object]] = field(default_factory=list)
    # Buffered events so a late SSE subscriber can replay what already happened.
    _history: list[object] = field(default_factory=list)
    _finished: bool = False

    def to_snapshot(self) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            analysisId=self.analysis_id,
            status=self.status,
            listing=self.listing,
            marketVerdict=self.market_verdict,
            condition=self.condition,
            verdict=self.verdict,
            traceId=self.trace_id,
        )


@runtime_checkable
class AnalysisStore(Protocol):
    """Storage + event-bus interface. M1 swaps this for a Postgres/Redis impl."""

    async def create(self, analysis: Analysis) -> None: ...

    async def get(self, analysis_id: str) -> Optional[Analysis]: ...

    async def update(self, analysis: Analysis) -> None: ...

    async def publish(self, analysis_id: str, event: dict) -> None:
        """Push a serialized SSE event to all subscribers and history."""

    async def finish(self, analysis_id: str) -> None:
        """Signal that no more events will be published for this analysis."""

    async def subscribe(self, analysis_id: str) -> "asyncio.Queue[object]":
        """Return a fresh queue pre-loaded with buffered history."""

    async def unsubscribe(self, analysis_id: str, queue: "asyncio.Queue[object]") -> None: ...

    # Idempotency support (process-local for M0).
    async def get_by_idempotency_key(self, key: str) -> Optional[str]: ...

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None: ...


class InMemoryAnalysisStore:
    """Async-safe in-memory store guarded by a single lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[str, Analysis] = {}
        self._idempotency: dict[str, str] = {}

    async def create(self, analysis: Analysis) -> None:
        async with self._lock:
            self._items[analysis.analysis_id] = analysis

    async def get(self, analysis_id: str) -> Optional[Analysis]:
        async with self._lock:
            return self._items.get(analysis_id)

    async def update(self, analysis: Analysis) -> None:
        async with self._lock:
            self._items[analysis.analysis_id] = analysis

    async def publish(self, analysis_id: str, event: dict) -> None:
        async with self._lock:
            analysis = self._items.get(analysis_id)
            if analysis is None:
                return
            analysis._history.append(event)
            subscribers = list(analysis._subscribers)
        for queue in subscribers:
            queue.put_nowait(event)

    async def finish(self, analysis_id: str) -> None:
        async with self._lock:
            analysis = self._items.get(analysis_id)
            if analysis is None:
                return
            analysis._finished = True
            subscribers = list(analysis._subscribers)
        for queue in subscribers:
            queue.put_nowait(STREAM_END)

    async def subscribe(self, analysis_id: str) -> "asyncio.Queue[object]":
        queue: asyncio.Queue[object] = asyncio.Queue()
        async with self._lock:
            analysis = self._items.get(analysis_id)
            if analysis is None:
                # Unknown analysis: caller will close immediately.
                queue.put_nowait(STREAM_END)
                return queue
            # Replay history so a late subscriber sees prior events.
            for event in analysis._history:
                queue.put_nowait(event)
            if analysis._finished:
                queue.put_nowait(STREAM_END)
            else:
                analysis._subscribers.append(queue)
        return queue

    async def unsubscribe(self, analysis_id: str, queue: "asyncio.Queue[object]") -> None:
        async with self._lock:
            analysis = self._items.get(analysis_id)
            if analysis is not None and queue in analysis._subscribers:
                analysis._subscribers.remove(queue)

    async def get_by_idempotency_key(self, key: str) -> Optional[str]:
        async with self._lock:
            return self._idempotency.get(key)

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None:
        async with self._lock:
            self._idempotency[key] = analysis_id


# Process-wide singleton for M0 (DI override available for tests).
_store: InMemoryAnalysisStore | None = None


def get_store() -> AnalysisStore:
    global _store
    if _store is None:
        _store = InMemoryAnalysisStore()
    return _store
