"""Analysis orchestrator.

M0 emits a realistic STAGED sequence (extract -> comps -> condition ->
synthesize) using fixture data and the real eBay adapter + valuation engine.
Each stage persists a partial result into the store and publishes an SSE event,
so both the live stream and the GET resume path stay consistent.

The structure (a list of stage coroutines, each emitting its events) is what a
real implementation plugs into: replace the fixture/hardcoded bits with live
fetches and model calls in M1.
"""

from __future__ import annotations

import asyncio
import logging

from shouldibuy.core.config import get_settings
from shouldibuy.core.store import Analysis, AnalysisStore
from shouldibuy.domain.models import (
    ConditionDTO,
    ConditionEvent,
    ConditionFlag,
    ConditionMismatch,
    DoneEvent,
    ErrorEvent,
    ListingAttributes,
    ListingDTO,
    ListingParsedEvent,
    Location,
    MarketVerdictDTO,
    MarketVerdictEvent,
    Money,
    ProgressEvent,
    TypicalRange,
    VerdictDTO,
    VerdictEvent,
)
from shouldibuy.pipeline import valuation
from shouldibuy.sources.base import RawPayload
from shouldibuy.sources.ebay import EbayBrowseSource, load_fixture

logger = logging.getLogger(__name__)

# Hardcoded comparable prices for M0 so the valuation math is REAL.
# TODO(M1): produce these from a comps source (eBay sold listings, etc.).
_M0_COMP_PRICES: list[float] = [
    349.0, 369.0, 379.0, 389.0, 399.0, 405.0, 410.0, 425.0, 430.0, 449.0, 469.0,
]


def _confidence_for(comp_count: int) -> str:
    if comp_count >= 10:
        return "high"
    if comp_count >= 5:
        return "medium"
    if comp_count >= 1:
        return "low"
    return "none"


def _negotiation_message(
    state: str, asking: float, currency: str, low: float, high: float
) -> str:
    """Templated, deterministic negotiation copy (NOT model-generated in M0)."""
    sym = "$" if currency == "USD" else f"{currency} "
    if state in ("above", "well_above"):
        target = round((low + high) / 2.0)
        return (
            f"Comparable listings typically sell between {sym}{low:.0f} and "
            f"{sym}{high:.0f}. The {sym}{asking:.0f} asking price is on the high "
            f"side — consider offering around {sym}{target}."
        )
    if state == "below":
        return (
            f"At {sym}{asking:.0f} this is below the typical {sym}{low:.0f}-"
            f"{sym}{high:.0f} range. If condition checks out, it's a strong buy."
        )
    return (
        f"At {sym}{asking:.0f} this sits within the typical {sym}{low:.0f}-"
        f"{sym}{high:.0f} range. The price is fair; a small offer near "
        f"{sym}{low:.0f} is reasonable."
    )


async def run_analysis(
    analysis_id: str,
    url: str,
    store: AnalysisStore,
) -> None:
    """Run the M0 staged pipeline for one analysis.

    All events flow through ``store.publish`` (SSE) and the store is updated
    after each stage (GET snapshot). Always terminates with a ``done`` event
    via ``store.finish``.
    """
    settings = get_settings()
    delay = settings.stage_delay_seconds

    async def emit(event: object) -> None:
        # Pydantic models -> camelCase dict for the wire.
        payload = event.model_dump(by_alias=True)  # type: ignore[attr-defined]
        await store.publish(analysis_id, payload)

    analysis = await store.get(analysis_id)
    if analysis is None:
        logger.warning("run_analysis: unknown analysis %s", analysis_id)
        return

    try:
        # ---- Stage 1: extract ------------------------------------------- #
        analysis.status = "extracting"
        await store.update(analysis)
        await emit(ProgressEvent(stage="extracting", message="Reading the listing…"))
        await asyncio.sleep(delay)

        source = EbayBrowseSource()
        # M0 uses the golden fixture (no network) parsed via the real adapter.
        payload = RawPayload(
            source=source.name, url=url, data=load_fixture("item_iphone13.json")
        )
        normalized = source.parse(payload)

        listing = ListingDTO(
            title=normalized.title,
            category=normalized.category,
            attributes=ListingAttributes(
                brand=normalized.brand,
                model=normalized.model,
                storage=normalized.storage,
                conditionGrade=normalized.condition_grade,
            ),
            price=Money(amount=normalized.price_amount, currency=normalized.price_currency),
            conditionClaim=normalized.condition_claim,
            location=(
                Location(label=normalized.location_label)
                if normalized.location_label
                else None
            ),
            images=normalized.images,
        )
        analysis.listing = listing
        await store.update(analysis)
        await emit(ListingParsedEvent(listing=listing))

        # ---- Stage 2: comps --------------------------------------------- #
        analysis.status = "comping"
        await store.update(analysis)
        await emit(ProgressEvent(stage="comping", message="Comparing against the market…"))
        await asyncio.sleep(delay)

        comps = _M0_COMP_PRICES
        asking = normalized.price_amount
        currency = normalized.price_currency
        pct = valuation.percentile_of(asking, comps)
        low, high = valuation.typical_range(comps)
        state = valuation.classify_state(pct)

        market_verdict = MarketVerdictDTO(
            state=state,
            asking=Money(amount=asking, currency=currency),
            percentile=pct,
            typicalRange=TypicalRange(low=round(low, 2), high=round(high, 2), currency=currency),
            compCount=len(comps),
        )
        analysis.market_verdict = market_verdict
        await store.update(analysis)
        await emit(MarketVerdictEvent(marketVerdict=market_verdict))

        # ---- Stage 3: condition ----------------------------------------- #
        analysis.status = "conditioning"
        await store.update(analysis)
        await emit(ProgressEvent(stage="conditioning", message="Inspecting condition…"))
        await asyncio.sleep(delay)

        # Static for M0. TODO(M1): derive from image analysis + claim parsing.
        condition = ConditionDTO(
            flags=[
                ConditionFlag(
                    kind="cosmetic",
                    detail="Light scratches visible on the back glass.",
                    imageIndex=1,
                )
            ],
            mismatches=[
                ConditionMismatch(
                    claim="Battery health 87%",
                    evidence="No battery-health screenshot included in photos.",
                    imageIndex=None,
                )
            ],
        )
        analysis.condition = condition
        await store.update(analysis)
        await emit(ConditionEvent(condition=condition))

        # ---- Stage 4: synthesize ---------------------------------------- #
        analysis.status = "synthesizing"
        await store.update(analysis)
        await emit(ProgressEvent(stage="synthesizing", message="Forming a verdict…"))
        await asyncio.sleep(delay)

        # INVARIANT: numbers come from the valuation engine via market_verdict.
        headline = {
            "below": "Priced below the market — likely a good deal.",
            "fair": "Fairly priced for its condition.",
            "above": "Priced above typical market — room to negotiate.",
            "well_above": "Significantly overpriced versus comparables.",
            "unknown": "Not enough data for a confident verdict.",
        }[state]

        verdict = VerdictDTO(
            state=state,
            headline=headline,
            negotiationMessage=_negotiation_message(state, asking, currency, low, high),
            confidence=_confidence_for(len(comps)),  # type: ignore[arg-type]
        )
        analysis.verdict = verdict
        await store.update(analysis)
        await emit(VerdictEvent(verdict=verdict))

        # ---- Done ------------------------------------------------------- #
        analysis.status = "done"
        await store.update(analysis)
        await emit(DoneEvent())

    except Exception as exc:  # noqa: BLE001 — M0 fails the analysis gracefully.
        logger.exception("analysis %s failed", analysis_id)
        analysis.status = "failed"
        await store.update(analysis)
        await emit(ErrorEvent(message=f"Analysis failed: {exc}"))
    finally:
        await store.finish(analysis_id)


def make_analysis(analysis_id: str, trace_id: str) -> Analysis:
    """Construct a fresh queued Analysis record."""
    return Analysis(analysis_id=analysis_id, trace_id=trace_id, status="queued")
