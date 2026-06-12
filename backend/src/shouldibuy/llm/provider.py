"""LLM provider abstraction.

Defines the ``LLMProvider`` Protocol plus two implementations:

* ``DeterministicProvider`` — the DEFAULT. Offline, no-network, no API key. It
  reproduces the original templated negotiation copy exactly so the pipeline
  behaves identically without credentials (hermetic CI / demo).
* ``OpenAICompatibleProvider`` — calls an OpenAI-style ``/chat/completions``
  endpoint via ``httpx.AsyncClient``. Used only when ``LLM_API_KEY`` is set.

INVARIANT: providers only ever produce *wording*. Monetary figures are owned by
the valuation engine and templated/validated in ``synthesis.py`` — a provider's
output is never trusted for a number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Protocol
from typing import runtime_checkable

import httpx
import structlog

if TYPE_CHECKING:
    from dynaconf import Dynaconf

logger = structlog.get_logger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o-mini"


def currency_symbol(currency: str) -> str:
    """Map a currency code to a display symbol (USD -> ``$``)."""
    return "$" if currency == "USD" else f"{currency} "


def deterministic_negotiation_message(
    state: str, asking: float, currency: str, low: float, high: float
) -> str:
    """Templated, deterministic negotiation copy.

    This is the original M0 ``_negotiation_message`` template, moved here so the
    ``DeterministicProvider`` and the synthesis fallback share one source of
    truth. Numbers are formatted from the engine values only.
    """
    sym = currency_symbol(currency)
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


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM provider implements."""

    name: str

    async def complete(self, *, system: str, user: str) -> str:
        """Return a completion for the ``system``/``user`` prompt pair."""
        ...


class DeterministicProvider:
    """Offline, no-network provider — the default with no API key.

    ``complete`` ignores the free-text prompt and returns the deterministic
    template rendered from STRUCTURED hints embedded in the ``user`` payload by
    ``synthesis.build_prompt``. This keeps the engine numbers authoritative and
    the output byte-identical to the original M0 behavior.
    """

    name = "deterministic"

    async def complete(self, *, system: str, user: str) -> str:
        from shouldibuy.llm.synthesis import render_from_prompt

        return render_from_prompt(user)


class OpenAICompatibleProvider:
    """Calls an OpenAI-style ``/chat/completions`` endpoint.

    Only used when ``LLM_API_KEY`` is configured. The endpoint, model and key
    come from settings; the response text is treated as *wording only* and is
    sanitized by ``synthesis.py`` before any number is surfaced.
    """

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    async def complete(self, *, system: str, user: str) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM response contained no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("LLM response message had no string content")
        return content.strip()


def _read_llm_settings(settings: Dynaconf) -> tuple[str, str, str]:
    """Return ``(api_key, base_url, model)`` from top-level or ``[LLM]`` section."""
    section = getattr(settings, "LLM", None)

    def _get(top_name: str, sub_name: str, default: str) -> str:
        top = getattr(settings, top_name, None)
        if top:
            return str(top)
        if section is not None:
            value = getattr(section, sub_name, None)
            if value:
                return str(value)
        return default

    api_key = _get("LLM_API_KEY", "API_KEY", "")
    base_url = _get("LLM_BASE_URL", "BASE_URL", _DEFAULT_BASE_URL)
    model = _get("LLM_MODEL_NAME", "MODEL", _DEFAULT_MODEL)
    return api_key, base_url, model


def build_llm_provider(settings: Dynaconf) -> LLMProvider:
    """Build the configured provider.

    Returns an ``OpenAICompatibleProvider`` when ``LLM_API_KEY`` is set,
    otherwise the offline ``DeterministicProvider`` (the default that keeps
    behavior identical with no key).
    """
    api_key, base_url, model = _read_llm_settings(settings)
    if api_key:
        logger.info("LLM provider built", provider="openai_compatible", model=model)
        return OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=model)
    logger.info("LLM provider built", provider="deterministic")
    return DeterministicProvider()
