"""Internal analysis snapshot domain object.

A ``@dataclass`` (internal domain object, per house style) holding the mutable
state of one analysis. The repository owns these; the controller converts to the
``AnalysisSnapshot`` Pydantic DTO at the API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from shouldibuy.model.dtos import AnalysisSnapshot
from shouldibuy.model.dtos import AnalysisStatus
from shouldibuy.model.dtos import ConditionDTO
from shouldibuy.model.dtos import ListingDTO
from shouldibuy.model.dtos import MarketVerdictDTO
from shouldibuy.model.dtos import VerdictDTO


@dataclass
class Analysis:
    """Mutable record holding the current state of one analysis."""

    analysis_id: str
    trace_id: str
    status: AnalysisStatus = "queued"
    listing: ListingDTO | None = None
    market_verdict: MarketVerdictDTO | None = None
    condition: ConditionDTO | None = None
    verdict: VerdictDTO | None = None

    def to_snapshot(self) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            analysis_id=self.analysis_id,
            status=self.status,
            listing=self.listing,
            market_verdict=self.market_verdict,
            condition=self.condition,
            verdict=self.verdict,
            trace_id=self.trace_id,
        )
