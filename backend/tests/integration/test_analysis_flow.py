"""End-to-end test of the AnalysisService staged pipeline.

Drives the service directly (no network), draining the SSE event bus to assert
the exact event sequence and final snapshot, preserving the FE contract.
"""

from __future__ import annotations

import pytest

from shouldibuy.integrations.sources.ebay import EbayBrowseSource
from shouldibuy.integrations.sources.fallback_chain import SourceFallbackChain
from shouldibuy.repository.analysis_repository import STREAM_END
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository
from shouldibuy.service.analysis_service import AnalysisService

pytestmark = pytest.mark.integration


def _service() -> AnalysisService:
    chain = SourceFallbackChain(sources=[EbayBrowseSource()])
    repo = InMemoryAnalysisRepository()
    # Zero delay for a fast test.
    return AnalysisService(source_chain=chain, repository=repo, stage_delay_seconds=0.0)


async def test_full_event_sequence() -> None:
    service = _service()
    analysis_id = await service.create_analysis(
        "https://www.ebay.com/itm/256123456789"
    )

    # Subscribe and run to completion: drain until STREAM_END.
    queue = await service.repository.subscribe(analysis_id)
    types: list[str] = []
    events: list[dict] = []
    while True:
        item = await queue.get()
        if item is STREAM_END:
            break
        events.append(item)
        types.append(item["type"])

    assert types == [
        "progress",
        "listing_parsed",
        "progress",
        "market_verdict",
        "progress",
        "condition",
        "progress",
        "verdict",
        "done",
    ]

    # Numbers in the market verdict come from the valuation engine.
    mv = next(e for e in events if e["type"] == "market_verdict")["marketVerdict"]
    assert mv["asking"]["amount"] == 419.99
    assert mv["compCount"] == 11
    assert mv["typicalRange"]["low"] < 419.99 < mv["typicalRange"]["high"]

    # Final snapshot is done with a verdict.
    snapshot = await service.get_analysis(analysis_id)
    assert snapshot is not None
    assert snapshot.status == "done"
    assert snapshot.verdict is not None


async def test_idempotency_returns_same_id() -> None:
    service = _service()
    a1 = await service.create_analysis("https://www.ebay.com/itm/1", "key-1")
    a2 = await service.create_analysis("https://www.ebay.com/itm/1", "key-1")
    assert a1 == a2
