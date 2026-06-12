"""End-to-end test of the AnalysisService staged pipeline.

Drives the service directly (no network), draining the SSE event bus to assert
the exact event sequence and final snapshot, preserving the FE contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from shouldibuy.integrations.sources.ebay import EbayBrowseSource
from shouldibuy.integrations.sources.ebay import load_fixture
from shouldibuy.integrations.sources.ebay import parse_search
from shouldibuy.integrations.sources.fallback_chain import SourceFallbackChain
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.repository.analysis_repository import STREAM_END
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository
from shouldibuy.service.analysis_service import AnalysisService

pytestmark = pytest.mark.integration

_SUBJECT_URL = "https://www.ebay.com/itm/256123456789"


def _service() -> AnalysisService:
    chain = SourceFallbackChain(sources=[EbayBrowseSource()])
    repo = InMemoryAnalysisRepository()
    # Zero delay for a fast test.
    return AnalysisService(source_chain=chain, repository=repo, stage_delay_seconds=0.0)


def _mock_source() -> MagicMock:
    """A mock eBay source backed entirely by the golden fixtures.

    ``has_credentials`` is True so the service exercises the live ``search_comps``
    path (an AsyncMock returning the parsed search fixture) — no network. The
    sync ``parse``/``can_handle`` delegate to the real adapter.
    """
    item_fixture = load_fixture("item_iphone13.json")
    search_comps = parse_search(load_fixture("search_iphone13.json"))
    real = EbayBrowseSource()

    source = MagicMock()
    source.name = "ebay"
    source.capabilities = EbayBrowseSource.capabilities
    source.has_credentials = True
    source.can_handle.return_value = True
    # parse is pure/sync — delegate to the real adapter.
    source.parse.side_effect = real.parse
    source.fetch = AsyncMock(
        return_value=RawPayload(source="ebay", url=_SUBJECT_URL, data=item_fixture)
    )
    source.search_comps = AsyncMock(return_value=search_comps)
    return source


def _service_with_mock(source: MagicMock) -> AnalysisService:
    chain = SourceFallbackChain(sources=[source])
    repo = InMemoryAnalysisRepository()
    return AnalysisService(source_chain=chain, repository=repo, stage_delay_seconds=0.0)


async def test_full_event_sequence() -> None:
    service = _service()
    analysis_id = await service.create_analysis("https://www.ebay.com/itm/256123456789")

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


async def _drain(service: AnalysisService, analysis_id: str) -> list[dict]:
    queue = await service.repository.subscribe(analysis_id)
    events: list[dict] = []
    while True:
        item = await queue.get()
        if item is STREAM_END:
            break
        events.append(item)
    return events


async def test_async_mock_source_drives_real_comp_count() -> None:
    """An AsyncMock eBay source (with creds) exercises search_comps.

    The pipeline must (a) emit the exact event sequence, (b) call search_comps,
    and (c) report compCount equal to the REAL comp count after self-exclusion
    and de-dup — here the 12-item search fixture minus the subject = 11.
    """
    source = _mock_source()
    service = _service_with_mock(source)
    analysis_id = await service.create_analysis(_SUBJECT_URL)
    events = await _drain(service, analysis_id)

    assert [e["type"] for e in events] == [
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

    # The live search path was exercised (not the fixture fallback).
    source.search_comps.assert_awaited_once()

    # The real comp count: 12 search results minus the subject listing.
    expected_comps = parse_search(load_fixture("search_iphone13.json"))
    subject_title = load_fixture("item_iphone13.json")["title"].strip().lower()
    expected_count = sum(
        1 for c in expected_comps if (c.title or "").strip().lower() != subject_title
    )
    assert expected_count == 11

    mv = next(e for e in events if e["type"] == "market_verdict")["marketVerdict"]
    assert mv["compCount"] == expected_count
    assert mv["asking"]["amount"] == 419.99
    assert mv["typicalRange"]["low"] < 419.99 < mv["typicalRange"]["high"]


async def test_idempotency_returns_same_id() -> None:
    service = _service()
    a1 = await service.create_analysis("https://www.ebay.com/itm/1", "key-1")
    a2 = await service.create_analysis("https://www.ebay.com/itm/1", "key-1")
    assert a1 == a2


def _mock_serpapi_source() -> MagicMock:
    """A mock comps-only fallback source (SerpAPI-shaped)."""
    from shouldibuy.integrations.sources import serpapi as serpapi_module
    from shouldibuy.integrations.sources.serpapi import SerpApiSource

    comps = serpapi_module.parse_search(
        serpapi_module.load_fixture("search_iphone13.json")
    )
    source = MagicMock()
    source.name = "serpapi"
    source.capabilities = SerpApiSource.capabilities
    source.has_credentials = True
    source.can_handle.return_value = False
    source.search_comps = AsyncMock(return_value=comps)
    return source


async def test_comp_fallback_uses_secondary_source_when_primary_fails() -> None:
    """Primary comps fail -> the comps-only fallback source supplies them.

    The eBay source raises on ``search_comps`` (e.g. Browse API outage); the
    pipeline must degrade to the SerpAPI-shaped source and still produce a
    market verdict from REAL fallback comps — not the bundled fixture.
    """
    primary = _mock_source()
    primary.search_comps = AsyncMock(side_effect=RuntimeError("browse api down"))
    fallback = _mock_serpapi_source()

    chain = SourceFallbackChain(sources=[primary, fallback])
    repo = InMemoryAnalysisRepository()
    service = AnalysisService(
        source_chain=chain, repository=repo, stage_delay_seconds=0.0
    )

    analysis_id = await service.create_analysis(_SUBJECT_URL)
    events = await _drain(service, analysis_id)

    primary.search_comps.assert_awaited_once()
    fallback.search_comps.assert_awaited_once()

    mv = next(e for e in events if e["type"] == "market_verdict")["marketVerdict"]
    # 11 priced fixture results; the Pro / Mini variants and the case are
    # excluded by the variant filter -> fewer comps than the eBay fixture path.
    assert mv["compCount"] > 0
    assert mv["asking"]["amount"] == 419.99


async def test_comp_fallback_skips_uncredentialed_sources() -> None:
    """Sources without credentials are never attempted live.

    With no credentialed comp source at all, the pipeline falls back to the
    bundled eBay search fixture (the offline/demo seam) and still completes.
    """
    primary = _mock_source()
    primary.has_credentials = False
    fallback = _mock_serpapi_source()
    fallback.has_credentials = False

    chain = SourceFallbackChain(sources=[primary, fallback])
    repo = InMemoryAnalysisRepository()
    service = AnalysisService(
        source_chain=chain, repository=repo, stage_delay_seconds=0.0
    )

    analysis_id = await service.create_analysis(_SUBJECT_URL)
    events = await _drain(service, analysis_id)

    primary.search_comps.assert_not_awaited()
    fallback.search_comps.assert_not_awaited()

    types = [e["type"] for e in events]
    assert types[-1] == "done"
    mv = next(e for e in events if e["type"] == "market_verdict")["marketVerdict"]
    assert mv["compCount"] == 11  # bundled fixture path
