"""Contract test for the eBay Browse adapter.

Loads the golden fixture and asserts ``parse`` produces the expected normalized
shape. No network access occurs — ``parse`` is pure.
"""

from __future__ import annotations

from shouldibuy.sources.base import Capability, NormalizedListing, RawPayload, SourceStatus
from shouldibuy.sources.ebay import EbayBrowseSource, load_fixture


def test_extract_item_id() -> None:
    source = EbayBrowseSource()
    assert source.extract_item_id("https://www.ebay.com/itm/256123456789") == "256123456789"
    assert (
        source.extract_item_id("https://www.ebay.com/itm/Apple-iPhone-13/256123456789?hash=x")
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


def test_parse_is_pure_no_network(monkeypatch) -> None:
    """parse must not touch the network even if httpx is broken."""
    import httpx

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("parse() must not make network calls")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    source = EbayBrowseSource()
    payload = RawPayload(source="ebay", url="x", data=load_fixture("item_iphone13.json"))
    listing = source.parse(payload)
    assert listing.price_amount == 419.99
