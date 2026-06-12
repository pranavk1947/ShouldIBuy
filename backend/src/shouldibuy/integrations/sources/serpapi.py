"""SerpAPI (Google Shopping) source adapter — comps-only fallback.

SerpAPI cannot fetch or parse an individual marketplace listing, so this
adapter advertises only ``Capability.COMPS`` and ``can_handle`` is always
``False`` for listing URLs. The orchestrator therefore never routes a listing
fetch here; it uses the adapter purely as a fallback *comp source* when the
primary (eBay Browse) comp search is unavailable or fails. This is the
degraded-capability path the ``Source`` SDK was designed for: partial sources
declare what they can do and the pipeline composes around them.

``parse_search`` is pure (payload dict in, ``Comp`` list out) so it is
unit-tested against the golden fixture with no network access — the same
contract-test pattern as the eBay adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import structlog

from shouldibuy.integrations.sources.provider import Capability
from shouldibuy.integrations.sources.provider import Comp
from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.integrations.sources.provider import SourceStatus

logger = structlog.get_logger(__name__)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "serpapi"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a golden SerpAPI payload fixture by file name."""
    path = _FIXTURE_DIR / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class SerpApiSource:
    """Adapter for SerpAPI's Google Shopping engine (comps only).

    Authentication is a simple ``api_key`` query parameter — no OAuth dance —
    which is exactly why it makes a good *fallback*: fewer moving parts than
    the primary source, at the cost of coarser data (no condition filters, no
    sold-listing signal, mixed retailers).
    """

    name = "serpapi"
    capabilities = frozenset({Capability.COMPS})
    status = SourceStatus.ACTIVE

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://serpapi.com/search.json",
        engine: str = "google_shopping",
        gl: str = "us",
        search_limit: int = 12,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._engine = engine
        self._gl = gl
        self._search_limit = search_limit
        self._client = client

    @property
    def has_credentials(self) -> bool:
        """Whether live network calls are possible (API key configured)."""
        return bool(self._api_key)

    # --------------------------------------------------------------------- #
    # URL handling — comps-only source: never claims a listing URL.
    # --------------------------------------------------------------------- #

    def can_handle(self, url: str) -> bool:
        return False

    async def fetch(self, url: str) -> RawPayload:
        """Not supported: SerpAPI cannot fetch an individual listing.

        The orchestrator never calls this because ``can_handle`` is ``False``;
        the explicit error documents the capability boundary.
        """
        raise NotImplementedError(
            "SerpApiSource is comps-only (Capability.COMPS); it cannot fetch "
            "individual listings."
        )

    def parse(self, payload: RawPayload) -> NormalizedListing:
        """Not supported: see ``fetch``."""
        raise NotImplementedError(
            "SerpApiSource is comps-only (Capability.COMPS); it cannot parse "
            "individual listings."
        )

    # --------------------------------------------------------------------- #
    # Network: Google Shopping search
    # --------------------------------------------------------------------- #

    async def search_comps(
        self, query: str, *, limit: int | None = None, filters: dict[str, Any]
    ) -> list[Comp]:
        """Search Google Shopping for comparable listings and map to ``Comp``.

        Google Shopping has no equivalent of eBay's ``conditionIds`` filter, so
        only the price band from ``filters`` is honored — applied client-side in
        ``parse_search`` via ``price_min``/``price_max``. The currency is taken
        on trust from the requested ``gl`` market (results carry no per-item
        currency field).
        """
        if not self.has_credentials:
            raise RuntimeError("SerpAPI key is not configured")

        effective_limit = limit or self._search_limit
        params: dict[str, str] = {
            "engine": self._engine,
            "q": query,
            "gl": self._gl,
            "num": str(effective_limit),
            "api_key": self._api_key,
        }
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.get(self._base_url, params=params)
            resp.raise_for_status()
            return parse_search(
                resp.json(),
                price_min=_as_float(filters.get("priceMin")),
                price_max=_as_float(filters.get("priceMax")),
                currency=str(filters.get("priceCurrency", "USD")),
                limit=effective_limit,
            )
        finally:
            if self._client is None:
                await client.aclose()


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_search(
    payload: dict[str, Any],
    *,
    price_min: float | None = None,
    price_max: float | None = None,
    currency: str = "USD",
    limit: int | None = None,
) -> list[Comp]:
    """Map a Google Shopping response to a list of ``Comp`` (pure).

    Items without a usable ``extracted_price`` are skipped; the optional price
    band is applied here because the upstream API cannot. Comps from a fallback
    source carry a reduced ``weight`` so the valuation engine can discount them
    relative to primary-source comps.
    """
    comps: list[Comp] = []
    for item in payload.get("shopping_results", []) or []:
        raw_value = (item or {}).get("extracted_price")
        if raw_value is None:
            continue
        try:
            amount = float(raw_value)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        if price_min is not None and amount < price_min:
            continue
        if price_max is not None and amount > price_max:
            continue
        comps.append(
            Comp(
                price=amount,
                currency=currency,
                title=item.get("title"),
                sold=False,
                weight=0.8,  # fallback-source comps count slightly less.
            )
        )
        if limit is not None and len(comps) >= limit:
            break
    return comps
