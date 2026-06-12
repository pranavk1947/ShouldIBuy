"""eBay Browse API source adapter.

M1 wires the live network path:

* ``_get_oauth_token`` performs the OAuth2 client-credentials grant and caches
  the resulting token (with expiry). It accepts an injected ``TokenCache`` (the
  Redis repository implements it) and otherwise falls back to an in-process
  cache so a single process still avoids re-minting tokens on every request.
* ``fetch`` extracts the legacy item id from a listing URL and calls the Browse
  API ``getItem`` endpoint, returning a ``RawPayload``.
* ``search_comps`` calls the Browse API ``item_summary/search`` endpoint and maps
  the result to ``Comp`` objects via the pure ``parse_search`` function.

``parse`` and ``parse_search`` are pure (payload dict in, dataclass out) so they
can be unit-tested against the golden fixtures with no network access. The
adapter has no credentials by default, which lets the service layer fall back to
the bundled fixtures for offline/demo runs (``has_credentials``).
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any
from typing import Protocol

import httpx
import structlog

from shouldibuy.integrations.sources.provider import Capability
from shouldibuy.integrations.sources.provider import Comp
from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.integrations.sources.provider import SourceStatus

logger = structlog.get_logger(__name__)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ebay"

# eBay item URLs look like https://www.ebay.com/itm/256123456789?...
_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{6,})")

_OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

# A small safety margin so we refresh before the token actually expires.
_TOKEN_EXPIRY_SKEW_SECONDS = 60


def load_fixture(name: str) -> dict[str, Any]:
    """Load a golden eBay payload fixture by file name."""
    path = _FIXTURE_DIR / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class TokenCache(Protocol):
    """Minimal cache contract for the OAuth application token.

    The Redis repository implements this so the token survives across processes;
    callers without Redis get the adapter's in-process fallback.
    """

    async def get_oauth_token(self) -> str | None:
        """Return a cached, non-expired token or ``None``."""
        ...

    async def set_oauth_token(self, token: str, ttl_seconds: int) -> None:
        """Store ``token`` with a TTL in seconds."""
        ...


class EbayBrowseSource:
    """Adapter for the eBay Buy Browse API."""

    name = "ebay"
    capabilities = frozenset(
        {
            Capability.ASKING,
            Capability.ATTRIBUTES,
            Capability.IMAGES,
            Capability.CONDITION_CLAIM,
            Capability.COMPS,
        }
    )
    status = SourceStatus.ACTIVE

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        oauth_url: str = "https://api.ebay.com/identity/v1/oauth2/token",
        browse_base_url: str = "https://api.ebay.com/buy/browse/v1",
        marketplace_id: str = "EBAY_US",
        search_limit: int = 12,
        client: httpx.AsyncClient | None = None,
        token_cache: TokenCache | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._browse_base_url = browse_base_url
        self._marketplace_id = marketplace_id
        self._search_limit = search_limit
        self._client = client
        self._token_cache = token_cache
        # In-process token fallback (used when no TokenCache is injected).
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def has_credentials(self) -> bool:
        """Whether live network calls are possible (creds configured)."""
        return bool(self._client_id and self._client_secret)

    # --------------------------------------------------------------------- #
    # URL handling
    # --------------------------------------------------------------------- #

    def can_handle(self, url: str) -> bool:
        return "ebay." in url and self.extract_item_id(url) is not None

    @staticmethod
    def extract_item_id(url: str) -> str | None:
        """Extract the numeric legacy item id from an eBay listing URL."""
        match = _ITEM_ID_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def to_browse_item_id(legacy_item_id: str) -> str:
        """Map a legacy numeric item id to the Browse API item id form."""
        return f"v1|{legacy_item_id}|0"

    # --------------------------------------------------------------------- #
    # OAuth (client-credentials grant, cached)
    # --------------------------------------------------------------------- #

    async def _get_oauth_token(self) -> str:
        """Return a cached application OAuth token or mint a fresh one.

        Uses an injected ``TokenCache`` when present, otherwise an in-process
        cache. The client-credentials grant authenticates with a base64-encoded
        ``client_id:client_secret`` Basic header and requests the public API
        scope.
        """
        if not self.has_credentials:
            raise RuntimeError("eBay OAuth credentials are not configured")

        if self._token_cache is not None:
            cached = await self._token_cache.get_oauth_token()
            if cached:
                return cached
        else:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token

        token, expires_in = await self._mint_token()

        ttl = max(1, expires_in - _TOKEN_EXPIRY_SKEW_SECONDS)
        if self._token_cache is not None:
            await self._token_cache.set_oauth_token(token, ttl)
        else:
            self._token = token
            self._token_expires_at = time.monotonic() + ttl
        return token

    async def _mint_token(self) -> tuple[str, int]:
        """Perform the client-credentials grant; return ``(token, expires_in)``."""
        creds = f"{self._client_id}:{self._client_secret}".encode()
        basic = base64.b64encode(creds).decode("ascii")
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.post(
                self._oauth_url,
                data={"grant_type": "client_credentials", "scope": _OAUTH_SCOPE},
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            resp.raise_for_status()
            body = resp.json()
            token: str = body["access_token"]
            expires_in = int(body.get("expires_in", 7200))
            return token, expires_in
        finally:
            if self._client is None:
                await client.aclose()

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
        }

    # --------------------------------------------------------------------- #
    # Network: getItem + item_summary/search
    # --------------------------------------------------------------------- #

    async def fetch(self, url: str) -> RawPayload:
        """Fetch a live item payload from the Browse API ``getItem`` endpoint."""
        item_id = self.extract_item_id(url)
        if item_id is None:
            raise ValueError(f"Not an eBay item URL: {url}")
        token = await self._get_oauth_token()
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.get(
                f"{self._browse_base_url}/item/{self.to_browse_item_id(item_id)}",
                headers=self._auth_headers(token),
            )
            resp.raise_for_status()
            return RawPayload(source=self.name, url=url, data=resp.json())
        finally:
            if self._client is None:
                await client.aclose()

    async def search_comps(
        self, query: str, *, limit: int | None = None, filters: dict[str, Any]
    ) -> list[Comp]:
        """Search the Browse API for comparable listings and map to ``Comp``.

        ``filters`` may carry ``conditionIds`` (a list) and a ``priceCurrency``
        plus ``priceMin``/``priceMax`` to constrain results. ``parse_search`` does
        the pure mapping so this method only handles the network call.
        """
        token = await self._get_oauth_token()
        effective_limit = limit or self._search_limit
        params: dict[str, str] = {"q": query, "limit": str(effective_limit)}
        filter_clause = _build_search_filter(filters)
        if filter_clause:
            params["filter"] = filter_clause

        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.get(
                f"{self._browse_base_url}/item_summary/search",
                params=params,
                headers=self._auth_headers(token),
            )
            resp.raise_for_status()
            return parse_search(resp.json())
        finally:
            if self._client is None:
                await client.aclose()

    # --------------------------------------------------------------------- #
    # Parsing (pure — fixture-driven, unit-tested)
    # --------------------------------------------------------------------- #

    def parse(self, payload: RawPayload) -> NormalizedListing:
        data = payload.data

        aspects = self._aspects(data)
        price = data.get("price", {}) or {}
        amount = float(price.get("value", 0.0))
        currency = price.get("currency", "USD")

        category = self._leaf_category(data.get("categoryPath", ""))
        images = self._images(data)
        location = self._location(data.get("itemLocation"))

        return NormalizedListing(
            title=data.get("title", ""),
            category=category or "Unknown",
            price_amount=amount,
            price_currency=currency,
            brand=aspects.get("brand") or data.get("brand"),
            model=aspects.get("model"),
            storage=aspects.get("storage capacity") or aspects.get("storage"),
            condition_grade=data.get("condition"),
            condition_claim=data.get("conditionDescription"),
            location_label=location,
            images=images,
            comps=[],  # comps come from ``search_comps`` in the pipeline.
        )

    # --------------------------------------------------------------------- #
    # Parsing helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _aspects(data: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for aspect in data.get("localizedAspects", []) or []:
            name = str(aspect.get("name", "")).strip().lower()
            value = aspect.get("value")
            if name and value is not None:
                result[name] = str(value)
        return result

    @staticmethod
    def _leaf_category(category_path: str) -> str:
        if not category_path:
            return ""
        return category_path.split("|")[-1].strip()

    @staticmethod
    def _images(data: dict[str, Any]) -> list[str]:
        images: list[str] = []
        primary = (data.get("image") or {}).get("imageUrl")
        if primary:
            images.append(primary)
        for extra in data.get("additionalImages", []) or []:
            url = (extra or {}).get("imageUrl")
            if url:
                images.append(url)
        return images

    @staticmethod
    def _location(item_location: dict[str, Any] | None) -> str | None:
        if not item_location:
            return None
        parts = [
            item_location.get("city"),
            item_location.get("stateOrProvince"),
            item_location.get("country"),
        ]
        label = ", ".join(p for p in parts if p)
        return label or None


def _build_search_filter(filters: dict[str, Any]) -> str:
    """Build the Browse API ``filter`` query clause from a filters dict.

    Supports ``conditionIds`` (list) and ``priceMin``/``priceMax`` (with
    ``priceCurrency``). The clauses are comma-joined per the Browse API syntax.
    """
    clauses: list[str] = []
    condition_ids = filters.get("conditionIds") or filters.get("condition_ids")
    if condition_ids:
        joined = "|".join(str(c) for c in condition_ids)
        clauses.append(f"conditionIds:{{{joined}}}")

    price_min = filters.get("priceMin")
    price_max = filters.get("priceMax")
    if price_min is not None or price_max is not None:
        lo = "" if price_min is None else f"{price_min}"
        hi = "" if price_max is None else f"{price_max}"
        clauses.append(f"price:[{lo}..{hi}]")
        currency = filters.get("priceCurrency", "USD")
        clauses.append(f"priceCurrency:{currency}")

    return ",".join(clauses)


def parse_search(payload: dict[str, Any]) -> list[Comp]:
    """Map an ``item_summary/search`` response to a list of ``Comp`` (pure).

    Items missing a usable price are skipped. The subject listing is NOT removed
    here (the pipeline owns de-duplication / self-exclusion).
    """
    comps: list[Comp] = []
    for summary in payload.get("itemSummaries", []) or []:
        price = (summary or {}).get("price") or {}
        raw_value = price.get("value")
        if raw_value is None:
            continue
        try:
            amount = float(raw_value)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        currency = price.get("currency", "USD")
        title = summary.get("title")
        comps.append(Comp(price=amount, currency=currency, title=title))
    return comps
