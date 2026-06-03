"""Domain DTOs and shared enums (camelCase wire format).

All JSON is camelCase. An alias generator keeps Python-side attributes
snake_case while the wire format matches the FE contract exactly. Models accept
both the alias and the field name on input (``populate_by_name=True``).

These are byte-for-byte equivalent in field names/aliases to the original
``domain/models.py`` so the existing FE contract is preserved.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

# --------------------------------------------------------------------------- #
# Enums (as Literals so they serialize as plain strings)
# --------------------------------------------------------------------------- #

MarketState = Literal["below", "fair", "above", "well_above", "unknown"]
VerdictState = MarketState
Confidence = Literal["high", "medium", "low", "none"]
AnalysisStatus = Literal[
    "queued",
    "extracting",
    "comping",
    "conditioning",
    "synthesizing",
    "done",
    "degraded",
    "failed",
]
Stage = Literal["extracting", "comping", "conditioning", "synthesizing"]


class CamelModel(BaseModel):
    """Base model emitting camelCase JSON, accepting either casing on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --------------------------------------------------------------------------- #
# Shared value objects
# --------------------------------------------------------------------------- #


class Money(CamelModel):
    amount: float
    currency: str


class ListingAttributes(CamelModel):
    brand: str | None = None
    model: str | None = None
    storage: str | None = None
    condition_grade: str | None = None


class Location(CamelModel):
    label: str


class TypicalRange(CamelModel):
    low: float
    high: float
    currency: str


# --------------------------------------------------------------------------- #
# Primary DTOs
# --------------------------------------------------------------------------- #


class ListingDTO(CamelModel):
    title: str
    category: str
    attributes: ListingAttributes
    price: Money
    condition_claim: str | None = None
    location: Location | None = None
    images: list[str] = Field(default_factory=list)


class MarketVerdictDTO(CamelModel):
    state: MarketState
    asking: Money
    percentile: int | None = None
    typical_range: TypicalRange | None = None
    comp_count: int


class ConditionFlag(CamelModel):
    kind: str
    detail: str
    image_index: int | None = None


class ConditionMismatch(CamelModel):
    claim: str
    evidence: str
    image_index: int | None = None


class ConditionDTO(CamelModel):
    flags: list[ConditionFlag] = Field(default_factory=list)
    mismatches: list[ConditionMismatch] = Field(default_factory=list)


class VerdictDTO(CamelModel):
    state: VerdictState
    headline: str
    negotiation_message: str
    confidence: Confidence


# --------------------------------------------------------------------------- #
# HTTP request / response shapes
# --------------------------------------------------------------------------- #


class AnalysisOptions(CamelModel):
    force_fresh: bool = False


class CreateAnalysisRequest(CamelModel):
    url: str
    options: AnalysisOptions | None = None


class CreateAnalysisResponse(CamelModel):
    analysis_id: str
    status: AnalysisStatus


class AnalysisSnapshot(CamelModel):
    analysis_id: str
    status: AnalysisStatus
    listing: ListingDTO | None = None
    market_verdict: MarketVerdictDTO | None = None
    condition: ConditionDTO | None = None
    verdict: VerdictDTO | None = None
    trace_id: str
