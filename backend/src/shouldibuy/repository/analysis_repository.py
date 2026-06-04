"""Analysis repository + per-analysis SSE event bus (was ``core/store.py``).

M0 ships an in-memory, async-safe implementation behind ``AnalysisRepository``
(a ``Protocol``). M1 adds a ``RedisAnalysisRepository`` that persists the
analysis snapshot as JSON, implements the eBay ``TokenCache`` Protocol, and adds
comp-cache + idempotency helpers — while KEEPING the in-process ``asyncio.Queue``
event bus for SSE (Redis is NOT used for streaming). ``InMemoryAnalysisRepository``
remains the default. Idempotency-by-key and the late-subscriber history replay
behavior are preserved exactly.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import runtime_checkable

import structlog

from shouldibuy.model.analysis import Analysis
from shouldibuy.model.dtos import AnalysisStatus
from shouldibuy.model.dtos import ConditionDTO
from shouldibuy.model.dtos import ListingDTO
from shouldibuy.model.dtos import MarketVerdictDTO
from shouldibuy.model.dtos import VerdictDTO

if TYPE_CHECKING:
    from shouldibuy.integrations.sources.provider import Comp

logger = structlog.get_logger(__name__)

# Sentinel pushed onto an analysis queue to signal "no more events".
STREAM_END = object()


@runtime_checkable
class AnalysisRepository(Protocol):
    """Storage + event-bus interface. M1 swaps this for a Postgres/Redis impl."""

    async def create(self, analysis: Analysis) -> None: ...

    async def get(self, analysis_id: str) -> Analysis | None: ...

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
    async def get_by_idempotency_key(self, key: str) -> str | None: ...

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

    async def get(self, analysis_id: str) -> Analysis | None:
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

    async def unsubscribe(self, analysis_id: str, queue: asyncio.Queue[object]) -> None:
        async with self._lock:
            subs = self._subscribers.get(analysis_id)
            if subs is not None and queue in subs:
                subs.remove(queue)

    async def get_by_idempotency_key(self, key: str) -> str | None:
        async with self._lock:
            return self._idempotency.get(key)

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None:
        async with self._lock:
            self._idempotency[key] = analysis_id


# --------------------------------------------------------------------------- #
# Redis-backed repository (M1)
# --------------------------------------------------------------------------- #


def _analysis_to_json(analysis: Analysis) -> str:
    """Serialize an Analysis snapshot to JSON (camelCase DTO payloads)."""
    payload: dict[str, Any] = {
        "analysisId": analysis.analysis_id,
        "traceId": analysis.trace_id,
        "status": analysis.status,
        "listing": (
            analysis.listing.model_dump(by_alias=True) if analysis.listing else None
        ),
        "marketVerdict": (
            analysis.market_verdict.model_dump(by_alias=True)
            if analysis.market_verdict
            else None
        ),
        "condition": (
            analysis.condition.model_dump(by_alias=True) if analysis.condition else None
        ),
        "verdict": (
            analysis.verdict.model_dump(by_alias=True) if analysis.verdict else None
        ),
    }
    return json.dumps(payload, separators=(",", ":"))


def _analysis_from_json(raw: str) -> Analysis:
    """Rehydrate an Analysis from its JSON snapshot."""
    data: dict[str, Any] = json.loads(raw)
    status: AnalysisStatus = data["status"]
    return Analysis(
        analysis_id=data["analysisId"],
        trace_id=data["traceId"],
        status=status,
        listing=(
            ListingDTO.model_validate(data["listing"]) if data.get("listing") else None
        ),
        market_verdict=(
            MarketVerdictDTO.model_validate(data["marketVerdict"])
            if data.get("marketVerdict")
            else None
        ),
        condition=(
            ConditionDTO.model_validate(data["condition"])
            if data.get("condition")
            else None
        ),
        verdict=(
            VerdictDTO.model_validate(data["verdict"]) if data.get("verdict") else None
        ),
    )


class RedisAnalysisRepository:
    """Redis-backed ``AnalysisRepository`` + eBay ``TokenCache``.

    Snapshots persist as JSON in Redis (so GET survives a restart), while the
    SSE event bus stays in-process (an ``asyncio.Queue`` per subscriber) — Redis
    is deliberately NOT used for streaming. Also provides:

    * ``get_oauth_token`` / ``set_oauth_token`` — the eBay ``TokenCache``.
    * ``get_cached_comps`` / ``set_cached_comps`` — comp cache keyed by the
      canonical query, with a TTL from settings.
    * idempotency-key -> analysisId mapping.

    These extra methods are concrete (not on the ``AnalysisRepository`` Protocol)
    so the service contract is unchanged.
    """

    _KEY_PREFIX = "shouldibuy"

    def __init__(
        self,
        redis_url: str,
        *,
        comp_cache_ttl_seconds: int = 3600,
        client: Any | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._comp_cache_ttl = comp_cache_ttl_seconds
        if client is not None:
            self._redis = client
        else:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url, decode_responses=True)
        # In-process event bus (NOT Redis) — mirrors the in-memory repo.
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[asyncio.Queue[object]]] = {}
        self._history: dict[str, list[object]] = {}
        self._finished: set[str] = set()

    # ---- key helpers ------------------------------------------------------ #

    def _analysis_key(self, analysis_id: str) -> str:
        return f"{self._KEY_PREFIX}:analysis:{analysis_id}"

    def _idempotency_key(self, key: str) -> str:
        return f"{self._KEY_PREFIX}:idem:{key}"

    def _comp_key(self, canonical_key: str) -> str:
        return f"{self._KEY_PREFIX}:comps:{canonical_key}"

    @property
    def _token_key(self) -> str:
        return f"{self._KEY_PREFIX}:ebay:oauth_token"

    # ---- AnalysisRepository: persistence --------------------------------- #

    async def create(self, analysis: Analysis) -> None:
        await self._redis.set(
            self._analysis_key(analysis.analysis_id), _analysis_to_json(analysis)
        )
        async with self._lock:
            self._subscribers.setdefault(analysis.analysis_id, [])
            self._history.setdefault(analysis.analysis_id, [])

    async def get(self, analysis_id: str) -> Analysis | None:
        raw = await self._redis.get(self._analysis_key(analysis_id))
        if raw is None:
            return None
        return _analysis_from_json(raw)

    async def update(self, analysis: Analysis) -> None:
        await self._redis.set(
            self._analysis_key(analysis.analysis_id), _analysis_to_json(analysis)
        )

    # ---- AnalysisRepository: in-process event bus ------------------------ #

    async def publish(self, analysis_id: str, event: dict) -> None:
        async with self._lock:
            self._history.setdefault(analysis_id, []).append(event)
            subscribers = list(self._subscribers.get(analysis_id, []))
        for queue in subscribers:
            queue.put_nowait(event)

    async def finish(self, analysis_id: str) -> None:
        async with self._lock:
            self._finished.add(analysis_id)
            subscribers = list(self._subscribers.get(analysis_id, []))
        for queue in subscribers:
            queue.put_nowait(STREAM_END)

    async def subscribe(self, analysis_id: str) -> asyncio.Queue[object]:
        queue: asyncio.Queue[object] = asyncio.Queue()
        exists = await self._redis.exists(self._analysis_key(analysis_id))
        async with self._lock:
            if not exists and analysis_id not in self._history:
                queue.put_nowait(STREAM_END)
                return queue
            for event in self._history.get(analysis_id, []):
                queue.put_nowait(event)
            if analysis_id in self._finished:
                queue.put_nowait(STREAM_END)
            else:
                self._subscribers.setdefault(analysis_id, []).append(queue)
        return queue

    async def unsubscribe(self, analysis_id: str, queue: asyncio.Queue[object]) -> None:
        async with self._lock:
            subs = self._subscribers.get(analysis_id)
            if subs is not None and queue in subs:
                subs.remove(queue)

    # ---- AnalysisRepository: idempotency --------------------------------- #

    async def get_by_idempotency_key(self, key: str) -> str | None:
        result = await self._redis.get(self._idempotency_key(key))
        return result if result is None else str(result)

    async def set_idempotency_key(self, key: str, analysis_id: str) -> None:
        await self._redis.set(self._idempotency_key(key), analysis_id)

    # ---- TokenCache (eBay OAuth) ----------------------------------------- #

    async def get_oauth_token(self) -> str | None:
        result = await self._redis.get(self._token_key)
        return result if result is None else str(result)

    async def set_oauth_token(self, token: str, ttl_seconds: int) -> None:
        await self._redis.set(self._token_key, token, ex=ttl_seconds)

    # ---- Comp cache ------------------------------------------------------- #

    async def get_cached_comps(self, canonical_key: str) -> list[Comp] | None:
        """Return cached comps for a canonical query key, or ``None``."""
        from shouldibuy.integrations.sources.provider import Comp

        raw = await self._redis.get(self._comp_key(canonical_key))
        if raw is None:
            return None
        items: list[dict[str, Any]] = json.loads(raw)
        return [Comp(**item) for item in items]

    async def set_cached_comps(self, canonical_key: str, comps: list[Comp]) -> None:
        """Cache comps for a canonical query key with the configured TTL."""
        payload = json.dumps([asdict(c) for c in comps], separators=(",", ":"))
        await self._redis.set(
            self._comp_key(canonical_key), payload, ex=self._comp_cache_ttl
        )

    async def aclose(self) -> None:
        """Close the underlying Redis connection (best-effort)."""
        close = getattr(self._redis, "aclose", None) or getattr(
            self._redis, "close", None
        )
        if close is not None:
            await close()
