"""eBay Browse API source adapter (was ``sources/ebay.py``).

The ``parse`` method is fully implemented and works purely on a payload dict
(the eBay ``getItem`` response shape), so it can be unit-tested against the
golden fixture with no network access. ``fetch`` / OAuth are stubbed with the
real httpx wiring sketched out but NOT exercised in tests.

The adapter is constructed with its eBay config (DI-friendly) rather than
reaching for a global ``get_settings()`` — ``startup.build_source_chain`` injects
the values.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from shouldibuy.integrations.sources.provider import Capability
from shouldibuy.integrations.sources.provider import NormalizedListing
from shouldibuy.integrations.sources.provider import RawPayload
from shouldibuy.integrations.sources.provider import SourceStatus

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ebay"

# eBay item URLs look like https://www.ebay.com/itm/256123456789?...
_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{6,})")


def load_fixture(name: str) -> dict[str, Any]:
    """Load a golden eBay payload fixture by file name."""
    path = _FIXTURE_DIR / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class EbayBrowseSource:
    """Adapter for the eBay Buy Browse API."""

    name = "ebay"
    capabilities = frozenset(
        {
            Capability.ASKING,
            Capability.ATTRIBUTES,
            Capability.IMAGES,
            Capability.CONDITION_CLAIM,
        }
    )
    status = SourceStatus.ACTIVE

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        oauth_url: str = "https://api.ebay.com/identity/v1/oauth2/token",
        browse_base_url: str = "https://api.ebay.com/buy/browse/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._browse_base_url = browse_base_url
        self._client = client
        self._token: str | None = None

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

    # --------------------------------------------------------------------- #
    # Network (NOT exercised in tests) — TODO(M1): wire to live API
    # --------------------------------------------------------------------- #

    async def _get_oauth_token(self) -> str:
        """Fetch an application OAuth token (client-credentials grant).

        TODO(M1): cache token with expiry, handle refresh + rate limits.
        """
        if not self._client_id or not self._client_secret:
            raise RuntimeError("eBay OAuth credentials are not configured")
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.post(
                self._oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
                auth=(self._client_id, self._client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token: str = resp.json()["access_token"]
            self._token = token
            return token
        finally:
            if self._client is None:
                await client.aclose()

    async def fetch(self, url: str) -> RawPayload:
        """Fetch a live item payload from the Browse API.

        TODO(M1): real network path. M0 callers should use ``load_fixture`` +
        ``parse`` instead so no network call is made.
        """
        item_id = self.extract_item_id(url)
        if item_id is None:
            raise ValueError(f"Not an eBay item URL: {url}")
        token = self._token or await self._get_oauth_token()
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.get(
                f"{self._browse_base_url}/item/get_item_by_legacy_id",
                params={"legacy_item_id": item_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return RawPayload(source=self.name, url=url, data=resp.json())
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
            comps=[],  # TODO(M1): populate via Browse search for comps.
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
