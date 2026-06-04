"""Unit tests for the in-memory analysis repository + event bus."""

from __future__ import annotations

from shouldibuy.model.analysis import Analysis
from shouldibuy.repository.analysis_repository import STREAM_END
from shouldibuy.repository.analysis_repository import AnalysisRepository
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository


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
