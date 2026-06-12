"""Unit tests for the analysis repositories + event bus.

The in-memory tests always run. The Redis tests are marked ``integration`` and
SKIP when no Redis is reachable, so CI stays green without a live Redis.
"""

from __future__ import annotations

import pytest

from shouldibuy.model.analysis import Analysis
from shouldibuy.repository.analysis_repository import STREAM_END
from shouldibuy.repository.analysis_repository import AnalysisRepository
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository
from shouldibuy.repository.analysis_repository import RedisAnalysisRepository

_REDIS_URL = "redis://localhost:6379/15"


def _analysis(aid: str = "an_test") -> Analysis:
    return Analysis(analysis_id=aid, trace_id="trace_test")


async def test_protocol_conformance() -> None:
    repo = InMemoryAnalysisRepository()
    assert isinstance(repo, AnalysisRepository)


async def test_create_and_get() -> None:
    repo = InMemoryAnalysisRepository()
    await repo.create(_analysis())
    got = await repo.get("an_test")
    assert got is not None
    assert got.trace_id == "trace_test"
    assert await repo.get("missing") is None


async def test_idempotency_key_roundtrip() -> None:
    repo = InMemoryAnalysisRepository()
    assert await repo.get_by_idempotency_key("k1") is None
    await repo.set_idempotency_key("k1", "an_test")
    assert await repo.get_by_idempotency_key("k1") == "an_test"


async def test_publish_to_live_subscriber() -> None:
    repo = InMemoryAnalysisRepository()
    await repo.create(_analysis())
    queue = await repo.subscribe("an_test")
    await repo.publish("an_test", {"type": "progress"})
    await repo.finish("an_test")
    assert await queue.get() == {"type": "progress"}
    assert await queue.get() is STREAM_END


async def test_late_subscriber_replays_history() -> None:
    repo = InMemoryAnalysisRepository()
    await repo.create(_analysis())
    await repo.publish("an_test", {"type": "progress"})
    await repo.publish("an_test", {"type": "done"})
    await repo.finish("an_test")
    queue = await repo.subscribe("an_test")
    assert await queue.get() == {"type": "progress"}
    assert await queue.get() == {"type": "done"}
    assert await queue.get() is STREAM_END


async def test_subscribe_unknown_closes_immediately() -> None:
    repo = InMemoryAnalysisRepository()
    queue = await repo.subscribe("missing")
    assert await queue.get() is STREAM_END


# --------------------------------------------------------------------------- #
# Redis repository — serialization via an in-process fake client (always runs)
# --------------------------------------------------------------------------- #


class _FakeRedis:
    """Minimal async Redis stand-in covering the methods the repo uses."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0


def _redis_repo() -> RedisAnalysisRepository:
    return RedisAnalysisRepository(_REDIS_URL, client=_FakeRedis())


async def test_redis_protocol_conformance() -> None:
    assert isinstance(_redis_repo(), AnalysisRepository)


async def test_redis_snapshot_roundtrip() -> None:
    from shouldibuy.model.dtos import ListingAttributes
    from shouldibuy.model.dtos import ListingDTO
    from shouldibuy.model.dtos import Money

    repo = _redis_repo()
    analysis = _analysis()
    analysis.status = "extracting"
    analysis.listing = ListingDTO(
        title="Apple iPhone 13",
        category="Phones",
        attributes=ListingAttributes(brand="Apple", model="Apple iPhone 13"),
        price=Money(amount=419.99, currency="USD"),
    )
    await repo.create(analysis)
    got = await repo.get("an_test")
    assert got is not None
    assert got.status == "extracting"
    assert got.listing is not None
    assert got.listing.price.amount == 419.99
    assert await repo.get("missing") is None


async def test_redis_idempotency_and_token_and_comps() -> None:
    from shouldibuy.integrations.sources.provider import Comp

    repo = _redis_repo()
    await repo.set_idempotency_key("k1", "an_xyz")
    assert await repo.get_by_idempotency_key("k1") == "an_xyz"
    assert await repo.get_by_idempotency_key("missing") is None

    assert await repo.get_oauth_token() is None
    await repo.set_oauth_token("tok-123", ttl_seconds=60)
    assert await repo.get_oauth_token() == "tok-123"

    assert await repo.get_cached_comps("apple|iphone 13|128gb|used") is None
    comps = [Comp(price=349.0, currency="USD", title="A")]
    await repo.set_cached_comps("apple|iphone 13|128gb|used", comps)
    cached = await repo.get_cached_comps("apple|iphone 13|128gb|used")
    assert cached is not None
    assert cached[0].price == 349.0
    assert cached[0].title == "A"


async def test_redis_event_bus_in_process() -> None:
    repo = _redis_repo()
    await repo.create(_analysis())
    queue = await repo.subscribe("an_test")
    await repo.publish("an_test", {"type": "progress"})
    await repo.finish("an_test")
    assert await queue.get() == {"type": "progress"}
    assert await queue.get() is STREAM_END


# --------------------------------------------------------------------------- #
# Redis repository — live integration (SKIPPED when no Redis is reachable)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_redis_live_roundtrip() -> None:
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover
        pytest.skip("redis not installed")

    client = aioredis.from_url(_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001 — any connection error -> skip.
        pytest.skip("no Redis reachable at " + _REDIS_URL)

    repo = RedisAnalysisRepository(_REDIS_URL, client=client)
    try:
        await repo.create(_analysis("an_live"))
        got = await repo.get("an_live")
        assert got is not None
        assert got.trace_id == "trace_test"
        await repo.set_oauth_token("live-tok", ttl_seconds=30)
        assert await repo.get_oauth_token() == "live-tok"
    finally:
        await repo.aclose()
