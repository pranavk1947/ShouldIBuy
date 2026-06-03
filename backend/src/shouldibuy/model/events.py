"""SSE event union, discriminated by ``type``.

These are the wire-level events streamed over ``GET /api/analyses/{id}/events``.
Field names/aliases are identical to the original ``domain/models.py`` so the FE
contract is preserved exactly.
"""

from __future__ import annotations

from typing import Annotated
from typing import Literal

from pydantic import Field

from shouldibuy.model.dtos import CamelModel
from shouldibuy.model.dtos import ConditionDTO
from shouldibuy.model.dtos import ListingDTO
from shouldibuy.model.dtos import MarketVerdictDTO
from shouldibuy.model.dtos import Stage
from shouldibuy.model.dtos import VerdictDTO


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
    ProgressEvent
    | ListingParsedEvent
    | MarketVerdictEvent
    | ConditionEvent
    | VerdictEvent
    | ErrorEvent
    | DoneEvent,
    Field(discriminator="type"),
]
