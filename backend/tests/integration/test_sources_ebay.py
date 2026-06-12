"""Contract test for the eBay Browse adapter (ported).

Loads the golden fixture and asserts ``parse`` produces the expected normalized
shape. No network access occurs — ``parse`` is pure.
"""

from __future__ import annotations

import pytest

from shouldibuy.integrations.sources.ebay import EbayBrowseSource
from shouldibuy.integrations.sources.ebay import load_fixture
from shouldibuy.integrations.sources.ebay import parse_search
from shouldibuy.integrations.sources.provider import Capability
from shouldibuy.integrations.sources.provider import Comp
from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.integrations.sources.provider import SourceStatus

pytestmark = pytest.mark.integration


def test_extract_item_id() -> None:
    source = EbayBrowseSource()
    assert (
        source.extract_item_id("https://www.ebay.com/itm/256123456789")
        == "256123456789"
    )
    assert (
        source.extract_item_id(
            "https://www.ebay.com/itm/Apple-iPhone-13/256123456789?hash=x"
        )
        == "256123456789"
    )
    assert source.extract_item_id("https://example.com/foo") is None


def test_can_handle() -> None:
    source = EbayBrowseSource()
    assert source.can_handle("https://www.ebay.com/itm/256123456789") is True
    assert source.can_handle("https://www.craigslist.org/abc") is False


def test_source_metadata() -> None:
    source = EbayBrowseSource()
    assert source.name == "ebay"
    assert source.status is SourceStatus.ACTIVE
    assert Capability.ASKING in source.capabilities


def test_parse_fixture_produces_expected_listing() -> None:
    source = EbayBrowseSource()
    payload = RawPayload(
        source="ebay",
        url="https://www.ebay.com/itm/256123456789",
        data=load_fixture("item_iphone13.json"),
    )

    listing = source.parse(payload)

    assert isinstance(listing, NormalizedListing)
    assert listing.title == "Apple iPhone 13 128GB Midnight (Unlocked) - Good Condition"
    assert listing.category == "Cell Phones & Smartphones"
    assert listing.price_amount == 419.99
    assert listing.price_currency == "USD"
    assert listing.brand == "Apple"
    assert listing.model == "Apple iPhone 13"
    assert listing.storage == "128 GB"
    assert listing.condition_grade == "Used"
    assert listing.condition_claim is not None
    assert "87%" in listing.condition_claim
    assert listing.location_label == "Austin, TX, US"
    # Primary image + 3 additional = 4
    assert len(listing.images) == 4
    assert listing.images[0].startswith("https://")
    # M0 adapter does not yet emit comps.
    assert listing.comps == []


def test_parse_search_contract() -> None:
    """parse_search maps the search fixture to Comp objects (pure)."""
    comps = parse_search(load_fixture("search_iphone13.json"))

    # The fixture has 12 itemSummaries, all with usable prices.
    assert len(comps) == 12
    assert all(isinstance(c, Comp) for c in comps)
    assert all(c.currency == "USD" for c in comps)
    assert all(c.price > 0 for c in comps)

    # Prices are parsed from strings into floats.
    prices = sorted(c.price for c in comps)
    assert prices[0] == 349.0
    assert prices[-1] == 469.0
    # The subject listing's price is present (pipeline owns self-exclusion).
    assert 419.99 in {c.price for c in comps}


def test_parse_search_no_pro_variants_in_fixture() -> None:
    """The pure-13 fixture must not contain any Pro/Pro Max titles."""
    comps = parse_search(load_fixture("search_iphone13.json"))
    titles = " ".join((c.title or "") for c in comps).lower()
    assert "pro" not in titles
    assert "plus" not in titles


def test_parse_search_skips_items_without_price() -> None:
    """Items missing a usable price are skipped."""
    payload = {
        "itemSummaries": [
            {"title": "No price"},
            {"title": "Zero", "price": {"value": "0", "currency": "USD"}},
            {"title": "Bad", "price": {"value": "abc", "currency": "USD"}},
            {"title": "Good", "price": {"value": "100.00", "currency": "USD"}},
        ]
    }
    comps = parse_search(payload)
    assert len(comps) == 1
    assert comps[0].price == 100.0
    assert comps[0].title == "Good"


def test_parse_is_pure_no_network(monkeypatch) -> None:
    """parse must not touch the network even if httpx is broken."""
    import httpx

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("parse() must not make network calls")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    source = EbayBrowseSource()
    payload = RawPayload(
        source="ebay", url="x", data=load_fixture("item_iphone13.json")
    )
    listing = source.parse(payload)
    assert listing.price_amount == 419.99
