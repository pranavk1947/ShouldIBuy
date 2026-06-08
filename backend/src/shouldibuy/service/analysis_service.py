"""Analysis service (was ``pipeline/orchestrator.py``).

Drives the M0 staged pipeline (extract -> comps -> condition -> synthesize) for
one analysis. Each stage persists a partial result via the repository and emits
an SSE event so both the live stream and the GET resume path stay consistent.

Dependencies (the source fallback chain + analysis repository) are injected via
the constructor; the DI container wires them. The event sequence and DTO field
names are preserved EXACTLY to satisfy the FE contract.
"""

from __future__ import annotations

import asyncio
import secrets

import structlog

from shouldibuy.integrations.sources.fallback_chain import SourceFallbackChain
from shouldibuy.integrations.sources.provider import Comp
from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.llm.provider import DeterministicProvider
from shouldibuy.llm.provider import LLMProvider
from shouldibuy.llm.synthesis import VerdictContext
from shouldibuy.llm.synthesis import write_negotiation_message
from shouldibuy.model.analysis import Analysis
from shouldibuy.model.dtos import ConditionDTO
from shouldibuy.model.dtos import ConditionFlag
from shouldibuy.model.dtos import ConditionMismatch
from shouldibuy.model.dtos import Confidence
from shouldibuy.model.dtos import ListingAttributes
from shouldibuy.model.dtos import ListingDTO
from shouldibuy.model.dtos import Location
from shouldibuy.model.dtos import MarketVerdictDTO
from shouldibuy.model.dtos import Money
from shouldibuy.model.dtos import TypicalRange
from shouldibuy.model.dtos import VerdictDTO
from shouldibuy.model.events import ConditionEvent
from shouldibuy.model.events import DoneEvent
from shouldibuy.model.events import ErrorEvent
from shouldibuy.model.events import ListingParsedEvent
from shouldibuy.model.events import MarketVerdictEvent
from shouldibuy.model.events import ProgressEvent
from shouldibuy.model.events import VerdictEvent
from shouldibuy.repository.analysis_repository import AnalysisRepository
from shouldibuy.service import valuation
from shouldibuy.service.canonicalize import CanonicalQuery
from shouldibuy.service.canonicalize import canonicalize
from shouldibuy.service.canonicalize import matches_variant

logger = structlog.get_logger(__name__)

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# Search fixture used as the offline/demo fallback when the eBay source has no
# credentials configured (live-vs-fixture seam — see ``_gather_comps``).
_SEARCH_FIXTURE = "search_iphone13.json"


def _short_id(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_analysis_id() -> str:
    return f"an_{_short_id()}"


def new_trace_id() -> str:
    return f"trace_{_short_id(16)}"


def _confidence_for(comp_count: int) -> Confidence:
    if comp_count >= 10:
        return "high"
    if comp_count >= 5:
        return "medium"
    if comp_count >= 1:
        return "low"
    return "none"


class AnalysisService:
    """Creates analyses and runs the staged M0 pipeline."""

    def __init__(
        self,
        source_chain: SourceFallbackChain,
        repository: AnalysisRepository,
        stage_delay_seconds: float = 0.4,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self._source_chain = source_chain
        self._repository = repository
        self._stage_delay = stage_delay_seconds
        # Default to the offline deterministic provider so behavior with no
        # LLM_API_KEY is identical to M0 (template-driven negotiation copy).
        self._llm_provider: LLMProvider = llm_provider or DeterministicProvider()
        # Track background tasks so they aren't garbage-collected mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def repository(self) -> AnalysisRepository:
        return self._repository

    async def create_analysis(
        self, url: str, idempotency_key: str | None = None
    ) -> str:
        """Create an analysis and kick off the in-process pipeline.

        Re-using an ``idempotency_key`` within the process returns the same
        analysisId without starting a second run.
        """
        if idempotency_key:
            existing = await self._repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        analysis_id = new_analysis_id()
        trace_id = new_trace_id()
        analysis = Analysis(analysis_id=analysis_id, trace_id=trace_id, status="queued")
        await self._repository.create(analysis)

        if idempotency_key:
            await self._repository.set_idempotency_key(idempotency_key, analysis_id)

        task = asyncio.create_task(self.run_analysis(analysis_id, url))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return analysis_id

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        return await self._repository.get(analysis_id)

    async def _gather_comps(
        self,
        source: object,
        canonical: CanonicalQuery,
        subject: NormalizedListing,
    ) -> list[Comp]:
        """Resolve comparable listings for the subject (real comps).

        Live-vs-fixture seam: when the eBay source has credentials we call its
        ``search_comps`` (live Browse API); otherwise we parse the bundled search
        fixture via the source's pure ``parse_search`` so the pipeline still runs
        offline/in tests/demo. Results are de-duped, the subject listing is
        removed, and obvious model-variant matches (e.g. "Pro"/"Pro Max") are
        excluded. When the repository provides a comp cache it is consulted first
        and populated after a live fetch.
        """
        repo = self._repository
        cache_key = canonical.key.cache_key()

        get_cached = getattr(repo, "get_cached_comps", None)
        if get_cached is not None:
            cached = await get_cached(cache_key)
            if cached:
                return self._filter_comps(cached, subject)

        has_creds = bool(getattr(source, "has_credentials", False))
        raw_comps: list[Comp]
        if has_creds:
            search_comps = source.search_comps  # type: ignore[attr-defined]
            raw_comps = await search_comps(
                canonical.query,
                limit=None,
                filters=canonical.filters,
            )
            set_cached = getattr(repo, "set_cached_comps", None)
            if set_cached is not None and raw_comps:
                await set_cached(cache_key, raw_comps)
        else:
            # Offline/demo path: parse the bundled search fixture.
            from shouldibuy.integrations.sources.ebay import load_fixture
            from shouldibuy.integrations.sources.ebay import parse_search

            raw_comps = parse_search(load_fixture(_SEARCH_FIXTURE))

        return self._filter_comps(raw_comps, subject, canonical=canonical)

    @staticmethod
    def _filter_comps(
        comps: list[Comp],
        subject: NormalizedListing,
        canonical: CanonicalQuery | None = None,
    ) -> list[Comp]:
        """Drop the subject listing, exclude variants, and de-dup comps."""
        exclude_terms = canonical.exclude_terms if canonical else []
        subject_title = subject.title.strip().lower()
        seen: set[tuple[float, str | None]] = set()
        result: list[Comp] = []
        for comp in comps:
            title = (comp.title or "").strip()
            # Self-exclusion: skip the subject listing by exact title match.
            if title.lower() == subject_title:
                continue
            if matches_variant(title, exclude_terms):
                continue
            dedup_key = (comp.price, title.lower() or None)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            result.append(comp)
        return result

    async def run_analysis(self, analysis_id: str, url: str) -> None:
        """Run the M0 staged pipeline for one analysis.

        All events flow through ``repository.publish`` (SSE) and the repository
        is updated after each stage (GET snapshot). Always terminates with a
        ``done`` event via ``repository.finish``.
        """
        repo = self._repository
        delay = self._stage_delay

        async def emit(event: object) -> None:
            payload = event.model_dump(by_alias=True)  # type: ignore[attr-defined]
            await repo.publish(analysis_id, payload)

        analysis = await repo.get(analysis_id)
        if analysis is None:
            logger.warning("run_analysis: unknown analysis", analysis_id=analysis_id)
            return

        try:
            # ---- Stage 1: extract --------------------------------------- #
            analysis.status = "extracting"
            await repo.update(analysis)
            await emit(
                ProgressEvent(stage="extracting", message="Reading the listing…")
            )
            await asyncio.sleep(delay)

            source = self._source_chain.select(url) or self._source_chain.sources[0]
            # M0 uses the golden fixture (no network) parsed via the real adapter.
            from shouldibuy.integrations.sources.ebay import load_fixture

            payload = RawPayload(
                source=source.name,
                url=url,
                data=load_fixture("item_iphone13.json"),
            )
            normalized = source.parse(payload)

            listing = ListingDTO(
                title=normalized.title,
                category=normalized.category,
                attributes=ListingAttributes(
                    brand=normalized.brand,
                    model=normalized.model,
                    storage=normalized.storage,
                    condition_grade=normalized.condition_grade,
                ),
                price=Money(
                    amount=normalized.price_amount, currency=normalized.price_currency
                ),
                condition_claim=normalized.condition_claim,
                location=(
                    Location(label=normalized.location_label)
                    if normalized.location_label
                    else None
                ),
                images=normalized.images,
            )
            analysis.listing = listing
            await repo.update(analysis)
            await emit(ListingParsedEvent(listing=listing))

            # ---- Stage 2: comps ----------------------------------------- #
            analysis.status = "comping"
            await repo.update(analysis)
            await emit(
                ProgressEvent(stage="comping", message="Comparing against the market…")
            )
            await asyncio.sleep(delay)

            canonical = canonicalize(normalized)
            comp_objs = await self._gather_comps(source, canonical, normalized)
            comps = [c.price for c in comp_objs]
            asking = normalized.price_amount
            currency = normalized.price_currency
            pct = valuation.percentile_of(asking, comps)
            low, high = valuation.typical_range(comps)
            state = valuation.classify_state(pct)

            market_verdict = MarketVerdictDTO(
                state=state,
                asking=Money(amount=asking, currency=currency),
                percentile=pct,
                typical_range=TypicalRange(
                    low=round(low, 2), high=round(high, 2), currency=currency
                ),
                comp_count=len(comps),
            )
            analysis.market_verdict = market_verdict
            await repo.update(analysis)
            await emit(MarketVerdictEvent(market_verdict=market_verdict))

            # ---- Stage 3: condition ------------------------------------- #
            analysis.status = "conditioning"
            await repo.update(analysis)
            await emit(
                ProgressEvent(stage="conditioning", message="Inspecting condition…")
            )
            await asyncio.sleep(delay)

            # Static stub. TODO(M2): derive from image analysis + claim parsing.
            condition = ConditionDTO(
                flags=[
                    ConditionFlag(
                        kind="cosmetic",
                        detail="Light scratches visible on the back glass.",
                        image_index=1,
                    )
                ],
                mismatches=[
                    ConditionMismatch(
                        claim="Battery health 87%",
                        evidence="No battery-health screenshot included in photos.",
                        image_index=None,
                    )
                ],
            )
            analysis.condition = condition
            await repo.update(analysis)
            await emit(ConditionEvent(condition=condition))

            # ---- Stage 4: synthesize ------------------------------------ #
            analysis.status = "synthesizing"
            await repo.update(analysis)
            await emit(
                ProgressEvent(stage="synthesizing", message="Forming a verdict…")
            )
            await asyncio.sleep(delay)

            # INVARIANT: numbers come from the valuation engine via market_verdict.
            headline = {
                "below": "Priced below the market — likely a good deal.",
                "fair": "Fairly priced for its condition.",
                "above": "Priced above typical market — room to negotiate.",
                "well_above": "Significantly overpriced versus comparables.",
                "unknown": "Not enough data for a confident verdict.",
            }[state]

            # The LLM provider writes the *wording*; numbers come from the
            # valuation engine and are guarded inside write_negotiation_message.
            condition_flags = [
                f"{flag.kind}: {flag.detail}" for flag in condition.flags
            ]
            negotiation_message = await write_negotiation_message(
                self._llm_provider,
                verdict_context=VerdictContext(
                    state=state,
                    asking=asking,
                    low=low,
                    high=high,
                    currency=currency,
                    condition_flags=condition_flags,
                ),
            )
            verdict = VerdictDTO(
                state=state,
                headline=headline,
                negotiation_message=negotiation_message,
                confidence=_confidence_for(len(comps)),
            )
            analysis.verdict = verdict
            await repo.update(analysis)
            await emit(VerdictEvent(verdict=verdict))

            # ---- Done --------------------------------------------------- #
            analysis.status = "done"
            await repo.update(analysis)
            await emit(DoneEvent())

        except Exception as exc:  # noqa: BLE001 — M0 fails the analysis gracefully.
            logger.exception("analysis failed", analysis_id=analysis_id)
            analysis.status = "failed"
            await repo.update(analysis)
            await emit(ErrorEvent(message=f"Analysis failed: {exc}"))
        finally:
            await repo.finish(analysis_id)
