"""Unit tests for the LLM provider + no-hallucinated-number guard."""

from __future__ import annotations

from shouldibuy.llm.provider import DeterministicProvider
from shouldibuy.llm.provider import build_llm_provider
from shouldibuy.llm.provider import deterministic_negotiation_message
from shouldibuy.llm.synthesis import VerdictContext
from shouldibuy.llm.synthesis import write_negotiation_message


class _BadNumberProvider:
    """Provider stub that invents a wrong price (simulates hallucination)."""

    name = "bad-number"

    async def complete(self, *, system: str, user: str) -> str:
        # A plausible-sounding message with WRONG numbers and a foreign currency.
        return "Comparable listings sell around £9999; offer them £8888 instead."


class _GoodProvider:
    """Provider stub returning a valid message echoing the engine numbers."""

    name = "good"

    async def complete(self, *, system: str, user: str) -> str:
        return (
            "Comps run $400 to $500. The $560 asking is high — consider "
            "offering around $450."
        )


async def test_deterministic_provider_matches_template() -> None:
    provider = DeterministicProvider()
    context = VerdictContext(
        state="fair", asking=450.0, low=400.0, high=500.0, currency="USD"
    )
    message = await write_negotiation_message(provider, verdict_context=context)
    expected = deterministic_negotiation_message("fair", 450.0, "USD", 400.0, 500.0)
    assert message == expected
    assert "$450" in message
    assert "$400" in message
    assert "$500" in message


async def test_build_llm_provider_defaults_to_deterministic() -> None:
    class _Settings:
        LLM_API_KEY = ""
        LLM = None

    provider = build_llm_provider(_Settings())  # type: ignore[arg-type]
    assert isinstance(provider, DeterministicProvider)
    assert provider.name == "deterministic"


async def test_no_hallucinated_number_falls_back_to_engine() -> None:
    """A provider that returns a WRONG number must not leak into the message.

    The number guard fails (required engine figures absent / foreign currency
    present), so the deterministic template is used and the ENGINE numbers
    appear instead.
    """
    context = VerdictContext(
        state="above", asking=560.0, low=400.0, high=500.0, currency="USD"
    )
    message = await write_negotiation_message(
        _BadNumberProvider(), verdict_context=context
    )
    # The hallucinated numbers/currency are gone.
    assert "9999" not in message
    assert "8888" not in message
    assert "£" not in message
    # The engine numbers are present (fallback engaged).
    assert "$400" in message
    assert "$500" in message
    assert message == deterministic_negotiation_message(
        "above", 560.0, "USD", 400.0, 500.0
    )


async def test_valid_model_output_is_passed_through() -> None:
    """A model message that contains all engine numbers is kept as-is."""
    context = VerdictContext(
        state="above", asking=560.0, low=400.0, high=500.0, currency="USD"
    )
    message = await write_negotiation_message(_GoodProvider(), verdict_context=context)
    assert message == (
        "Comps run $400 to $500. The $560 asking is high — consider "
        "offering around $450."
    )
