"""LLM provider abstraction + synthesis layer.

The LLM layer writes the *prose* for the negotiation message while the
valuation engine remains the single source of truth for every monetary figure
(see ``shouldibuy.service.valuation``). The default provider is fully offline
and deterministic so CI, tests and demos stay hermetic with no API key.
"""

from __future__ import annotations

from shouldibuy.llm.provider import DeterministicProvider
from shouldibuy.llm.provider import LLMProvider
from shouldibuy.llm.provider import OpenAICompatibleProvider
from shouldibuy.llm.provider import build_llm_provider
from shouldibuy.llm.synthesis import VerdictContext
from shouldibuy.llm.synthesis import write_negotiation_message

__all__ = [
    "DeterministicProvider",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "VerdictContext",
    "build_llm_provider",
    "write_negotiation_message",
]
