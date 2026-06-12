"""Canonicalize a normalized listing into a comp-search query (pure).

Given a :class:`NormalizedListing` (currently tuned for phones), produce a
:class:`CanonicalQuery` carrying:

* a free-text ``query`` string for the Browse API ``q`` parameter
  (e.g. ``"Apple iPhone 13 128GB"``),
* a structured ``key`` (brand/model/storage/condition) used for cache keys and
  de-duplication, and
* Browse API ``filters`` (``conditionIds``, an optional price band, currency).

Strict variant handling: a subject "iPhone 13" must NOT pull in "iPhone 13 Pro"
or "Pro Max" comps. We capture the exact model token and a list of
``exclude_terms`` so the pipeline can filter out variant matches after search.

Everything here is a pure function: data in, dataclass out, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field

from shouldibuy.integrations.sources.provider import NormalizedListing

# eBay Browse conditionId values (numeric) keyed by a normalized grade label.
# https://developer.ebay.com/devzone/finding/callref/enums/conditionIdList.html
_CONDITION_IDS: dict[str, list[int]] = {
    "new": [1000],
    "open box": [1500],
    "openbox": [1500],
    "certified refurbished": [2000],
    "refurbished": [2000, 2010, 2020, 2030],
    "used": [3000],
    "good": [3000],
    "very good": [3000],
    "acceptable": [3000],
    "for parts or not working": [7000],
}

# Default condition filter when the grade is unknown/used: the "used" family.
_DEFAULT_CONDITION_IDS: list[int] = [3000]

# Variant tokens that must NOT bleed into a base-model comp set.
_VARIANT_TERMS: tuple[str, ...] = ("Pro Max", "Pro", "Plus", "Mini", "Max")

# Price band width as a fraction of the asking price (+/-).
_PRICE_BAND_FRACTION = 0.35


@dataclass(frozen=True)
class CanonicalKey:
    """Structured identity for a listing used for caching + de-dup."""

    brand: str | None
    model: str | None
    storage: str | None
    condition: str | None

    def cache_key(self) -> str:
        """A stable, lowercase cache key for the comp set."""
        parts = [
            (self.brand or "").strip().lower(),
            (self.model or "").strip().lower(),
            (self.storage or "").strip().lower(),
            (self.condition or "").strip().lower(),
        ]
        return "|".join(parts)


@dataclass(frozen=True)
class CanonicalQuery:
    """A canonicalized comp-search request derived from a listing."""

    query: str
    key: CanonicalKey
    filters: dict[str, object]
    exclude_terms: list[str] = field(default_factory=list)


def _normalize_storage(storage: str | None) -> str | None:
    """Collapse "128 GB" / "128gb" -> "128GB"; pass through otherwise."""
    if not storage:
        return None
    match = re.search(r"(\d+)\s*(gb|tb)", storage, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"
    return storage.strip()


def _condition_ids(condition_grade: str | None) -> list[int]:
    if not condition_grade:
        return list(_DEFAULT_CONDITION_IDS)
    key = condition_grade.strip().lower()
    return list(_CONDITION_IDS.get(key, _DEFAULT_CONDITION_IDS))


def _exclude_terms_for(model: str | None) -> list[str]:
    """Variant terms to exclude unless the subject model itself contains them.

    For a base "iPhone 13" we exclude "Pro", "Pro Max", etc. But if the subject
    is itself an "iPhone 13 Pro", we keep "Pro" (and only exclude the broader
    "Pro Max").
    """
    if not model:
        return list(_VARIANT_TERMS)
    model_lower = model.lower()
    return [term for term in _VARIANT_TERMS if term.lower() not in model_lower]


def matches_variant(title: str | None, exclude_terms: list[str]) -> bool:
    """True if ``title`` contains an excluded variant token (word-boundary)."""
    if not title:
        return False
    lowered = title.lower()
    for term in exclude_terms:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, lowered):
            return True
    return False


def canonicalize(listing: NormalizedListing) -> CanonicalQuery:
    """Derive a :class:`CanonicalQuery` from a normalized listing (pure).

    The query string concatenates brand + model + normalized storage, falling
    back to the listing title when structured attributes are missing. The model
    is de-duplicated against the brand so "Apple" + "Apple iPhone 13" renders as
    "Apple iPhone 13" rather than "Apple Apple iPhone 13".
    """
    brand = (listing.brand or "").strip() or None
    model = (listing.model or "").strip() or None
    storage = _normalize_storage(listing.storage)
    condition = (listing.condition_grade or "").strip() or None

    query_parts: list[str] = []
    if brand:
        query_parts.append(brand)
    if model:
        # Avoid "Apple Apple iPhone 13" when model already carries the brand.
        if brand and model.lower().startswith(brand.lower()):
            query_parts[-1] = model
        else:
            query_parts.append(model)
    if storage:
        query_parts.append(storage)

    query = " ".join(query_parts).strip()
    if not query:
        query = listing.title.strip()

    condition_ids = _condition_ids(condition)

    asking = listing.price_amount
    filters: dict[str, object] = {
        "conditionIds": condition_ids,
        "priceCurrency": listing.price_currency,
    }
    if asking and asking > 0:
        filters["priceMin"] = round(asking * (1.0 - _PRICE_BAND_FRACTION), 2)
        filters["priceMax"] = round(asking * (1.0 + _PRICE_BAND_FRACTION), 2)

    return CanonicalQuery(
        query=query,
        key=CanonicalKey(
            brand=brand,
            model=model,
            storage=storage,
            condition=condition,
        ),
        filters=filters,
        exclude_terms=_exclude_terms_for(model),
    )
