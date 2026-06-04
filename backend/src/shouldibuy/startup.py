"""Resource builders wired into the DI container during app startup.

Mirrors loop-scribe's ``startup.py`` ``build_*`` functions: each takes the
Dynaconf settings and returns a concrete implementation (or a sensible default),
keeping construction logic out of the container and the app module.
"""

from __future__ import annotations

import structlog
from dynaconf import Dynaconf

from shouldibuy.integrations.sources.ebay import EbayBrowseSource
from shouldibuy.integrations.sources.fallback_chain import SourceFallbackChain
from shouldibuy.integrations.sources.provider import Source
from shouldibuy.repository.analysis_repository import AnalysisRepository
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository

logger = structlog.get_logger(__name__)


def build_source_chain(settings: Dynaconf) -> SourceFallbackChain:
    """Build the source fallback chain from settings.

    M0 ships a single eBay adapter; the chain wraps it with retry +
    circuit-breaker so M1 can add more sources without touching callers.
    """
    ebay_section = getattr(settings, "EBAY", None)
    source = EbayBrowseSource(
        client_id=getattr(ebay_section, "CLIENT_ID", "") if ebay_section else "",
        client_secret=(
            getattr(ebay_section, "CLIENT_SECRET", "") if ebay_section else ""
        ),
        oauth_url=(
            getattr(
                ebay_section,
                "OAUTH_URL",
                "https://api.ebay.com/identity/v1/oauth2/token",
            )
            if ebay_section
            else "https://api.ebay.com/identity/v1/oauth2/token"
        ),
        browse_base_url=(
            getattr(
                ebay_section,
                "BROWSE_BASE_URL",
                "https://api.ebay.com/buy/browse/v1",
            )
            if ebay_section
            else "https://api.ebay.com/buy/browse/v1"
        ),
    )
    sources: list[Source] = [source]

    retry = settings.SOURCES.RETRY
    cb = settings.SOURCES.CIRCUIT_BREAKER
    chain = SourceFallbackChain(
        sources=sources,
        max_attempts=retry.MAX_ATTEMPTS,
        wait_min=retry.WAIT_MIN,
        wait_max=retry.WAIT_MAX,
        fail_max=cb.FAIL_MAX,
        reset_timeout=cb.RESET_TIMEOUT,
    )
    logger.info("Source fallback chain built", sources=[s.name for s in sources])
    return chain


def build_analysis_repository(settings: Dynaconf) -> AnalysisRepository:
    """Build the analysis repository.

    M0 uses an in-memory repository that doubles as the SSE event bus.
    TODO(M1): return a Postgres/Redis-backed repository based on settings.
    """
    logger.info("In-memory analysis repository built")
    return InMemoryAnalysisRepository()
