"""Source adapter SDK (was ``sources/base.py``).

A ``Source`` knows how to (a) recognize a listing URL it can handle,
(b) fetch a raw payload, and (c) ``parse`` that payload into a
``NormalizedListing``. Capability flags advertise what data a source can
provide so the orchestrator can degrade gracefully when a source is partial.

The ``parse`` step is intentionally pure (payload dict in, dataclass out) so it
can be unit-tested against golden fixtures with no network access.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Optional
from typing import Protocol
from typing import runtime_checkable


class Capability(str, enum.Enum):
    """What a source can supply for a listing."""

    ASKING = "asking"  # the seller's asking price
    ATTRIBUTES = "attributes"  # structured item specifics (brand/model/storage)
    IMAGES = "images"  # listing photos
    CONDITION_CLAIM = "condition_claim"  # seller-stated condition
    COMPS = "comps"  # comparable sold/active listings


class SourceStatus(str, enum.Enum):
    """Operational status of a source adapter."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"


@dataclass(frozen=True)
class RawPayload:
    """A fetched, source-specific payload prior to normalization."""

    source: str
    url: str
    data: dict[str, Any]


@dataclass
class Comp:
    """A comparable listing/sale used by the valuation engine."""

    price: float
    currency: str
    title: Optional[str] = None
    sold: bool = False
    weight: float = 1.0


@dataclass
class NormalizedListing:
    """Source-agnostic listing shape consumed by the pipeline."""

    title: str
    category: str
    price_amount: float
    price_currency: str
    brand: Optional[str] = None
    model: Optional[str] = None
    storage: Optional[str] = None
    condition_grade: Optional[str] = None
    condition_claim: Optional[str] = None
    location_label: Optional[str] = None
    images: list[str] = field(default_factory=list)
    comps: list[Comp] = field(default_factory=list)


@runtime_checkable
class Source(Protocol):
    """Protocol every data-source adapter implements."""

    name: str
    capabilities: frozenset[Capability]
    status: SourceStatus

    def can_handle(self, url: str) -> bool:
        """Return True if this source recognizes the listing URL."""
        ...

    async def fetch(self, url: str) -> RawPayload:
        """Fetch the raw payload for ``url`` (network). Not used in tests."""
        ...

    def parse(self, payload: RawPayload) -> NormalizedListing:
        """Normalize a raw payload. Pure; safe to unit-test with fixtures."""
        ...
