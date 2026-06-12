"""Contract tests for the SerpAPI (Google Shopping) comps-only adapter.

Mirrors ``test_sources_ebay.py``: the golden fixture drives the pure
``parse_search`` mapping with no network access. The fallback-ordering tests
exercise the orchestrator's comp-source degradation path with stub sources.
"""

from __future__ import annotations

import httpx
import pytest

from shouldibuy.integrations.sources.provider import Capability
from shouldibuy.integrations.sources.provider import Comp
from shouldibuy.integrations.sources.provider import SourceStatus
from shouldibuy.integrations.sources.serpapi import SerpApiSource
from shouldibuy.integrations.sources.serpapi import load_fixture
from shouldibuy.integrations.sources.serpapi import parse_search

pytestmark = pytest.mark.integration


def test_source_metadata() -> None:
    source = SerpApiSource()
    assert source.name == "serpapi"
    assert source.status is SourceStatus.ACTIVE
    assert source.capabilities == frozenset({Capability.COMPS})


def test_comps_only_source_never_claims_listing_urls() -> None:
    source = SerpApiSource(api_key="k")
    assert source.can_handle("https://www.ebay.com/itm/256123456789") is False
    assert source.can_handle("https://www.google.com/shopping/product/1") is False


def test_has_credentials() -> None:
    assert SerpApiSource().has_credentials is False
    assert SerpApiSource(api_key="k").has_credentials is True


@pytest.mark.asyncio
async def test_fetch_and_parse_raise_capability_boundary() -> None:
    source = SerpApiSource(api_key="k")
    with pytest.raises(NotImplementedError):
        await source.fetch("https://www.ebay.com/itm/256123456789")
    with pytest.raises(NotImplementedError):
        source.parse(None)  # type: ignore[arg-type]


def test_parse_search_contract() -> None:
    """Golden-fixture mapping: skip unpriced items, keep the rest, weight<1."""
    comps = parse_search(load_fixture("search_iphone13.json"))

    # 12 results, 1 without extracted_price -> 11 comps.
    assert len(comps) == 11
    assert all(isinstance(c, Comp) for c in comps)
    assert all(c.price > 0 for c in comps)
    assert all(c.currency == "USD" for c in comps)
    # Fallback-source comps are down-weighted for the valuation engine.
    assert all(c.weight == 0.8 for c in comps)


def test_parse_search_applies_price_band_client_side() -> None:
    """Google Shopping has no price filter; the band is applied in parse."""
    comps = parse_search(
        load_fixture("search_iphone13.json"), price_min=300.0, price_max=500.0
    )
    prices = [c.price for c in comps]
    # The $12.99 accessory and the $545 Pro variant are excluded by the band.
    assert all(300.0 <= p <= 500.0 for p in prices)
    assert 12.99 not in prices
    assert 545.0 not in prices


def test_parse_search_respects_limit() -> None:
    comps = parse_search(load_fixture("search_iphone13.json"), limit=5)
    assert len(comps) == 5


@pytest.mark.asyncio
async def test_search_comps_requires_credentials() -> None:
    source = SerpApiSource()
    with pytest.raises(RuntimeError, match="not configured"):
        await source.search_comps("iphone 13", filters={})


@pytest.mark.asyncio
async def test_search_comps_live_path_with_mock_transport() -> None:
    """The network seam: a mocked transport returns the golden fixture."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=load_fixture("search_iphone13.json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = SerpApiSource(api_key="test-key", client=client)

    comps = await source.search_comps(
        "Apple iPhone 13 128GB",
        filters={"priceMin": 300, "priceMax": 500, "priceCurrency": "USD"},
    )

    assert seen["engine"] == "google_shopping"
    assert seen["q"] == "Apple iPhone 13 128GB"
    assert seen["api_key"] == "test-key"
    assert comps
    assert all(300.0 <= c.price <= 500.0 for c in comps)
    await client.aclose()
