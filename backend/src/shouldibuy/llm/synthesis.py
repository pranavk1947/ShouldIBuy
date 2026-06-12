"""Synthesis layer — turns structured verdict inputs into negotiation prose.

The model (when one is configured) writes the *wording*; the valuation engine
owns the *numbers*. ``write_negotiation_message`` builds a prompt from STRUCTURED
inputs, calls the provider, and then GUARDS the result: the required engine
figures must be present and only the given currency symbol may appear, otherwise
it falls back to the deterministic template. This guarantees the function never
trusts a model for any number (no hallucinated prices).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field

import structlog

from shouldibuy.llm.provider import LLMProvider
from shouldibuy.llm.provider import currency_symbol
from shouldibuy.llm.provider import deterministic_negotiation_message
from shouldibuy.utils.observability.langsmith import traceable_if_enabled

logger = structlog.get_logger(__name__)

_PROMPT_MARKER = "STRUCTURED_INPUT="

_SYSTEM_PROMPT = (
    "You are a concise marketplace negotiation assistant. Write one short, "
    "actionable message (<= 320 characters) advising a buyer how to negotiate. "
    "Use ONLY the prices provided in the structured input — never invent numbers "
    "or currencies. Include a concrete offer or ask. Mention condition concerns "
    "when present."
)


@dataclass
class VerdictContext:
    """Structured inputs for synthesizing a negotiation message.

    All monetary values come from the valuation engine; the synthesis layer only
    ever formats or validates against these — never derives new ones.
    """

    state: str
    asking: float
    low: float
    high: float
    currency: str
    condition_flags: list[str] = field(default_factory=list)


def _target_offer(low: float, high: float) -> int:
    return round((low + high) / 2.0)


def _format_money(value: float, currency: str) -> str:
    return f"{currency_symbol(currency)}{value:.0f}"


def build_prompt(context: VerdictContext) -> str:
    """Build the user prompt.

    The structured input is embedded as JSON behind ``_PROMPT_MARKER`` so the
    offline ``DeterministicProvider`` can recover the exact engine numbers and
    render the deterministic template, while a real model gets a readable brief.
    """
    payload = {
        "state": context.state,
        "asking": context.asking,
        "low": context.low,
        "high": context.high,
        "currency": context.currency,
        "conditionFlags": context.condition_flags,
        "suggestedOffer": _target_offer(context.low, context.high),
    }
    flags = (
        "; ".join(context.condition_flags)
        if context.condition_flags
        else "none reported"
    )
    brief = (
        f"Market state: {context.state}. "
        f"Asking price: {_format_money(context.asking, context.currency)}. "
        f"Typical range: {_format_money(context.low, context.currency)} to "
        f"{_format_money(context.high, context.currency)}. "
        f"Condition concerns: {flags}. "
        "Write the negotiation message now."
    )
    return f"{brief}\n{_PROMPT_MARKER}{json.dumps(payload)}"


def _decode_prompt(user: str) -> VerdictContext | None:
    """Recover a ``VerdictContext`` from a prompt built by ``build_prompt``."""
    idx = user.find(_PROMPT_MARKER)
    if idx == -1:
        return None
    raw = user[idx + len(_PROMPT_MARKER) :].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return VerdictContext(
        state=str(payload["state"]),
        asking=float(payload["asking"]),
        low=float(payload["low"]),
        high=float(payload["high"]),
        currency=str(payload["currency"]),
        condition_flags=list(payload.get("conditionFlags", [])),
    )


def render_from_prompt(user: str) -> str:
    """Render the deterministic template from an encoded prompt.

    Used by ``DeterministicProvider.complete``. Falls back to echoing the prompt
    only if it was not produced by ``build_prompt`` (should not happen in flow).
    """
    context = _decode_prompt(user)
    if context is None:
        return user
    return deterministic_negotiation_message(
        context.state,
        context.asking,
        context.currency,
        context.low,
        context.high,
    )


def required_numbers(context: VerdictContext) -> list[str]:
    """Engine-formatted numbers that MUST appear in a valid message."""
    if context.state in ("above", "well_above"):
        offer = _target_offer(context.low, context.high)
        return [
            _format_money(context.low, context.currency),
            _format_money(context.high, context.currency),
            f"{currency_symbol(context.currency)}{offer}",
        ]
    return [
        _format_money(context.asking, context.currency),
        _format_money(context.low, context.currency),
        _format_money(context.high, context.currency),
    ]


def _passes_number_guard(message: str, context: VerdictContext) -> bool:
    """All required engine numbers present AND no foreign currency symbol."""
    for token in required_numbers(context):
        if token not in message:
            return False
    sym = currency_symbol(context.currency).strip()
    foreign = {"$", "£", "€", "¥"} - {sym}
    return not any(other and other in message for other in foreign)


@traceable_if_enabled(name="write_negotiation_message")
async def write_negotiation_message(
    provider: LLMProvider, *, verdict_context: VerdictContext
) -> str:
    """Synthesize the negotiation message.

    The provider writes the wording; this function GUARDS the output against
    hallucinated numbers/currencies. If the guard fails (e.g. a real model
    dropped or invented a figure), it falls back to the deterministic template
    so the surfaced numbers always originate from the valuation engine.
    """
    prompt = build_prompt(verdict_context)
    try:
        message = await provider.complete(system=_SYSTEM_PROMPT, user=prompt)
    except Exception:  # noqa: BLE001 — never fail the pipeline on LLM errors.
        logger.warning(
            "llm synthesis failed; using deterministic fallback",
            provider=getattr(provider, "name", "unknown"),
        )
        message = ""

    message = message.strip()
    if message and _passes_number_guard(message, verdict_context):
        return message

    if message:
        logger.warning(
            "llm output failed number guard; using deterministic fallback",
            provider=getattr(provider, "name", "unknown"),
        )
    return deterministic_negotiation_message(
        verdict_context.state,
        verdict_context.asking,
        verdict_context.currency,
        verdict_context.low,
        verdict_context.high,
    )
