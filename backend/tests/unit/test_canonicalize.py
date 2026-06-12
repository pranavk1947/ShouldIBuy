"""Unit tests for the pure canonicalization of listings into comp queries."""

from __future__ import annotations

from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.service.canonicalize import canonicalize
from shouldibuy.service.canonicalize import matches_variant


def _listing(**overrides: object) -> NormalizedListing:
    base: dict[str, object] = {
        "title": "Apple iPhone 13 128GB Midnight (Unlocked) - Good Condition",
        "category": "Cell Phones & Smartphones",
        "price_amount": 419.99,
        "price_currency": "USD",
        "brand": "Apple",
        "model": "Apple iPhone 13",
        "storage": "128 GB",
        "condition_grade": "Used",
    }
    base.update(overrides)
    return NormalizedListing(**base)  # type: ignore[arg-type]


def test_query_string_brand_model_storage() -> None:
    cq = canonicalize(_listing())
    # Brand de-duped against a model that already carries the brand.
    assert cq.query == "Apple iPhone 13 128GB"


def test_query_storage_normalized() -> None:
    cq = canonicalize(_listing(storage="128gb"))
    assert cq.query == "Apple iPhone 13 128GB"
    assert cq.key.storage == "128GB"


def test_query_falls_back_to_title_when_no_attributes() -> None:
    cq = canonicalize(
        _listing(brand=None, model=None, storage=None, title="Some Gadget XL")
    )
    assert cq.query == "Some Gadget XL"


def test_structured_key() -> None:
    cq = canonicalize(_listing())
    assert cq.key.brand == "Apple"
    assert cq.key.model == "Apple iPhone 13"
    assert cq.key.storage == "128GB"
    assert cq.key.condition == "Used"
    assert cq.key.cache_key() == "apple|apple iphone 13|128gb|used"


def test_filters_condition_and_price_band() -> None:
    cq = canonicalize(_listing())
    assert cq.filters["conditionIds"] == [3000]
    assert cq.filters["priceCurrency"] == "USD"
    # +/-35% band around 419.99.
    assert cq.filters["priceMin"] == 272.99
    assert cq.filters["priceMax"] == 566.99


def test_filters_new_condition_id() -> None:
    cq = canonicalize(_listing(condition_grade="New"))
    assert cq.filters["conditionIds"] == [1000]


def test_variant_exclusion_for_base_model() -> None:
    """A base 'iPhone 13' must exclude Pro / Pro Max / Plus / Mini."""
    cq = canonicalize(_listing(model="Apple iPhone 13"))
    assert "Pro" in cq.exclude_terms
    assert "Pro Max" in cq.exclude_terms

    assert matches_variant("Apple iPhone 13 Pro 128GB", cq.exclude_terms) is True
    assert matches_variant("Apple iPhone 13 Pro Max 256GB", cq.exclude_terms) is True
    # The base model itself must NOT be flagged as a variant.
    assert matches_variant("Apple iPhone 13 128GB Midnight", cq.exclude_terms) is False


def test_variant_exclusion_for_pro_model_keeps_pro() -> None:
    """A subject 'iPhone 13 Pro' keeps 'Pro' but still excludes 'Pro Max'."""
    cq = canonicalize(_listing(model="Apple iPhone 13 Pro"))
    assert "Pro" not in cq.exclude_terms
    assert "Pro Max" in cq.exclude_terms
    assert matches_variant("Apple iPhone 13 Pro Max", cq.exclude_terms) is True
    assert matches_variant("Apple iPhone 13 Pro 128GB", cq.exclude_terms) is False
