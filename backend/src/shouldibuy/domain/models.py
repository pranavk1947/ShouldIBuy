"""Domain DTOs, SSE event union, and enums.

All JSON is camelCase. We use an alias generator so Python-side attributes stay
snake_case while the wire format matches the FE contract exactly. Models accept
both the alias and the field name on input (``populate_by_name=True``).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
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


# --------------------------------------------------------------------------- #
# Base model — camelCase wire format
# --------------------------------------------------------------------------- #


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
    brand: Optional[str] = None
    model: Optional[str] = None
    storage: Optional[str] = None
    condition_grade: Optional[str] = None


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
    condition_claim: Optional[str] = None
    location: Optional[Location] = None
    images: list[str] = Field(default_factory=list)


class MarketVerdictDTO(CamelModel):
    state: MarketState
    asking: Money
    percentile: Optional[int] = None
    typical_range: Optional[TypicalRange] = None
    comp_count: int


class ConditionFlag(CamelModel):
    kind: str
    detail: str
    image_index: Optional[int] = None


class ConditionMismatch(CamelModel):
    claim: str
    evidence: str
    image_index: Optional[int] = None


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
    options: Optional[AnalysisOptions] = None


class CreateAnalysisResponse(CamelModel):
    analysis_id: str
    status: AnalysisStatus


class AnalysisSnapshot(CamelModel):
    analysis_id: str
    status: AnalysisStatus
    listing: Optional[ListingDTO] = None
    market_verdict: Optional[MarketVerdictDTO] = None
    condition: Optional[ConditionDTO] = None
    verdict: Optional[VerdictDTO] = None
    trace_id: str


# --------------------------------------------------------------------------- #
# SSE event union (discriminated by ``type``)
# --------------------------------------------------------------------------- #


class ProgressEvent(CamelModel):
    type: Literal["progress"] = "progress"
    stage: Stage
    message: str


class ListingParsedEvent(CamelModel):
    type: Literal["listing_parsed"] = "listing_parsed"
    listing: ListingDTO


class MarketVerdictEvent(CamelModel):
    type: Literal["market_verdict"] = "market_verdict"
    market_verdict: MarketVerdictDTO


class ConditionEvent(CamelModel):
    type: Literal["condition"] = "condition"
    condition: ConditionDTO


class VerdictEvent(CamelModel):
    type: Literal["verdict"] = "verdict"
    verdict: VerdictDTO


class ErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    message: str


class DoneEvent(CamelModel):
    type: Literal["done"] = "done"


SSEEvent = Annotated[
    Union[
        ProgressEvent,
        ListingParsedEvent,
        MarketVerdictEvent,
        ConditionEvent,
        VerdictEvent,
        ErrorEvent,
        DoneEvent,
    ],
    Field(discriminator="type"),
]
