"""Resource builders wired into the DI container during app startup.

Mirrors loop-scribe's ``startup.py`` ``build_*`` functions: each takes the
Dynaconf settings and returns a concrete implementation (or a sensible default),
keeping construction logic out of the container and the app module.
"""

from __future__ import annotations

import structlog
from dynaconf import Dynaconf

from shouldibuy.integrations.sources.ebay import EbayBrowseSource
from shouldibuy.integrations.sources.ebay import TokenCache
from shouldibuy.integrations.sources.fallback_chain import SourceFallbackChain
from shouldibuy.integrations.sources.provider import Source
from shouldibuy.repository.analysis_repository import AnalysisRepository
from shouldibuy.repository.analysis_repository import InMemoryAnalysisRepository
from shouldibuy.repository.analysis_repository import RedisAnalysisRepository

logger = structlog.get_logger(__name__)

_DEFAULT_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_DEFAULT_BROWSE_BASE_URL = "https://api.ebay.com/buy/browse/v1"


def build_source_chain(
    settings: Dynaconf, token_cache: TokenCache | None = None
) -> SourceFallbackChain:
    """Build the source fallback chain from settings.

    The chain wraps the eBay adapter with retry + circuit-breaker so M1 can add
    more sources without touching callers. When the eBay source is built with
    credentials and a ``token_cache`` (the Redis repo) is supplied, the cache is
    injected so the OAuth token survives across processes.
    """
    ebay_section = getattr(settings, "EBAY", None)
    client_id = getattr(ebay_section, "CLIENT_ID", "") if ebay_section else ""
    client_secret = getattr(ebay_section, "CLIENT_SECRET", "") if ebay_section else ""
    has_creds = bool(client_id and client_secret)
    search_section = getattr(ebay_section, "SEARCH", None) if ebay_section else None
    search_limit = int(getattr(search_section, "LIMIT", 12)) if search_section else 12
    source = EbayBrowseSource(
        client_id=client_id,
        client_secret=client_secret,
        oauth_url=(
            getattr(ebay_section, "OAUTH_URL", _DEFAULT_OAUTH_URL)
            if ebay_section
            else _DEFAULT_OAUTH_URL
        ),
        browse_base_url=(
            getattr(ebay_section, "BROWSE_BASE_URL", _DEFAULT_BROWSE_BASE_URL)
            if ebay_section
            else _DEFAULT_BROWSE_BASE_URL
        ),
        search_limit=search_limit,
        # Only wire the shared token cache when we can actually mint tokens.
        token_cache=token_cache if has_creds else None,
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

    Returns a ``RedisAnalysisRepository`` when ``REDIS_URL`` is configured (it
    persists the snapshot as JSON and also serves as the eBay token/comp cache),
    otherwise the in-memory repository that doubles as the SSE event bus. The
    in-memory repo remains the default for offline/test/demo runs.
    """
    redis_url = _redis_url(settings)
    if redis_url:
        comp_ttl = _comp_cache_ttl(settings)
        logger.info("Redis analysis repository built", redis_url=redis_url)
        return RedisAnalysisRepository(redis_url, comp_cache_ttl_seconds=comp_ttl)
    logger.info("In-memory analysis repository built")
    return InMemoryAnalysisRepository()


def _redis_url(settings: Dynaconf) -> str:
    """Read ``REDIS_URL`` from the top level or a ``[REDIS]`` section."""
    top = getattr(settings, "REDIS_URL", None)
    if top:
        return str(top)
    redis_section = getattr(settings, "REDIS", None)
    if redis_section is not None:
        url = getattr(redis_section, "URL", None)
        if url:
            return str(url)
    return ""


def _comp_cache_ttl(settings: Dynaconf) -> int:
    """Comp-cache TTL (seconds) from ``[EBAY.SEARCH] COMP_CACHE_TTL_SECONDS``."""
    ebay_section = getattr(settings, "EBAY", None)
    search_section = getattr(ebay_section, "SEARCH", None) if ebay_section else None
    if search_section is not None:
        ttl = getattr(search_section, "COMP_CACHE_TTL_SECONDS", None)
        if ttl is not None:
            return int(ttl)
    return 3600
