"""Ordered fallback chain of listing sources.

Mirrors loop-scribe's ``stt/fallback_chain.py``: each source gets its own
``pybreaker.CircuitBreaker`` and is called through a ``tenacity`` retry. The
chain tries each source in order until one succeeds, raising
``AllSourcesFailedError`` if every source fails.

In M0 the only source is the eBay adapter and ``fetch`` is fixture-backed at the
service layer, but the resilience wiring is real so M1 can drop in live network
fetches and additional sources without touching callers.
"""

from __future__ import annotations

import pybreaker
import structlog
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential_jitter

from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.integrations.sources.provider import Source
from shouldibuy.utils.observability.tracing import traced

logger = structlog.get_logger(__name__)


class AllSourcesFailedError(Exception):
    """Raised when all sources in the fallback chain fail."""

    def __init__(self, errors: list[tuple[str, Exception]]) -> None:
        self.errors = errors
        sources = ", ".join(name for name, _ in errors)
        super().__init__(f"All sources failed: {sources}")


class _CircuitBreakerLogger(pybreaker.CircuitBreakerListener):
    """Logs circuit breaker state transitions."""

    def state_change(
        self, cb: pybreaker.CircuitBreaker, old_state: object, new_state: object
    ) -> None:
        logger.warning(
            "Circuit breaker state changed",
            breaker=cb.name,
            old_state=old_state.name if hasattr(old_state, "name") else str(old_state),
            new_state=new_state.name if hasattr(new_state, "name") else str(new_state),
        )


class SourceFallbackChain:
    """Ordered fallback chain of sources with retry and circuit breaker."""

    def __init__(
        self,
        sources: list[Source],
        max_attempts: int = 3,
        wait_min: float = 0.5,
        wait_max: float = 4.0,
        fail_max: int = 5,
        reset_timeout: int = 30,
    ) -> None:
        self._entries: list[tuple[Source, pybreaker.CircuitBreaker]] = []
        cb_listener = _CircuitBreakerLogger()
        for source in sources:
            cb = pybreaker.CircuitBreaker(
                fail_max=fail_max,
                reset_timeout=reset_timeout,
                name=f"source-{source.name}",
                listeners=[cb_listener],
            )
            self._entries.append((source, cb))
        self._max_attempts = max_attempts
        self._wait_min = wait_min
        self._wait_max = wait_max

    @property
    def sources(self) -> list[Source]:
        """The ordered sources backing this chain."""
        return [source for source, _ in self._entries]

    def select(self, url: str) -> Source | None:
        """Return the first source that recognizes ``url`` (no network)."""
        for source, _ in self._entries:
            if source.can_handle(url):
                return source
        return None

    @traced("sources.fetch")
    async def fetch(self, url: str) -> RawPayload:
        """Try each source in order until one fetches successfully."""
        errors: list[tuple[str, Exception]] = []

        for source, cb in self._entries:
            if cb.current_state == pybreaker.STATE_OPEN:
                logger.warning("Circuit OPEN, skipping source", source=source.name)
                continue

            if not source.can_handle(url):
                continue

            logger.info("Attempting source fetch", source=source.name)
            try:
                return await self._call_with_retry(source, cb, url)
            except Exception as e:  # noqa: BLE001 — try the next source.
                logger.warning(
                    "Source failed, falling back",
                    source=source.name,
                    error=str(e),
                )
                errors.append((source.name, e))

        raise AllSourcesFailedError(errors)

    async def _call_with_retry(
        self,
        source: Source,
        cb: pybreaker.CircuitBreaker,
        url: str,
    ) -> RawPayload:
        """Call ``source.fetch`` with tenacity retry, recording CB failures.

        Uses pybreaker's internal state methods (``_handle_error`` /
        ``_handle_success``) rather than ``call_async`` for native asyncio
        compatibility — same approach as loop-scribe's STT chain.
        """

        @retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=self._wait_min, max=self._wait_max),
            retry=retry_if_exception_type((Exception,)),
            reraise=True,
        )
        async def _attempt() -> RawPayload:
            try:
                result = await source.fetch(url)
            except Exception as exc:
                try:
                    cb.state._handle_error(exc, reraise=False)
                except pybreaker.CircuitBreakerError:
                    logger.warning(
                        "Circuit breaker threshold reached, circuit now OPEN",
                        source=source.name,
                        reset_timeout=cb.reset_timeout,
                    )
                raise
            else:
                cb.state._handle_success()
                return result

        return await _attempt()
