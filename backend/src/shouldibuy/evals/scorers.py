"""Pure scorer functions for synthesis output.

Each scorer takes ``(message, case)`` and returns a ``(score, label)`` where
``score`` is a float in 0..1. Scorers are pure — no I/O, no network — so the
pytest eval gate and the LangSmith runner share identical scoring logic.

Hard scorers MUST pass for a case to be considered correct (these guard against
hallucinated numbers / currencies and unusable output). Soft scorers contribute
to the aggregate but a single soft miss should not fail the gate.
"""

from __future__ import annotations

from shouldibuy.evals.dataset import EvalCase
from shouldibuy.llm.provider import currency_symbol
from shouldibuy.llm.synthesis import required_numbers

_MAX_LENGTH = 320
_ACTIONABLE_TERMS = ("offer", "ask", "negotiat", "buy", "consider", "propose")
_ALL_CURRENCY_SYMBOLS = {"$", "£", "€", "¥"}

# Scorers whose failure invalidates a case (used by the pytest gate).
HARD_SCORERS = (
    "contains_engine_price",
    "within_length",
    "no_invented_currency",
    "is_actionable",
)


def contains_engine_price(message: str, case: EvalCase) -> tuple[float, str]:
    """1.0 iff every required engine number appears verbatim (anti-hallucination)."""
    needed = required_numbers(case.context)
    present = sum(1 for token in needed if token in message)
    score = present / len(needed) if needed else 1.0
    return score, "contains_engine_price"


def within_length(message: str, case: EvalCase) -> tuple[float, str]:
    """1.0 iff the message is within the length budget."""
    raw_limit = case.expectations.get("max_length", _MAX_LENGTH)
    limit = int(raw_limit) if isinstance(raw_limit, int) else _MAX_LENGTH
    return (1.0 if len(message) <= limit else 0.0), "within_length"


def mentions_condition_when_present(message: str, case: EvalCase) -> tuple[float, str]:
    """1.0 when no flags expected, else 1.0 iff a condition keyword appears.

    SOFT scorer: the deterministic template intentionally keeps numbers-only
    copy, so this rewards (but does not require) condition-aware wording.
    """
    if not case.expectations.get("expect_condition_mention"):
        return 1.0, "mentions_condition_when_present"
    lowered = message.lower()
    keywords = ("condition", "scratch", "battery", "scuff", "crack", "wear", "screen")
    hit = any(k in lowered for k in keywords)
    return (1.0 if hit else 0.0), "mentions_condition_when_present"


def no_invented_currency(message: str, case: EvalCase) -> tuple[float, str]:
    """1.0 iff only the case's currency symbol appears (no foreign symbols)."""
    sym = currency_symbol(case.context.currency).strip()
    foreign = _ALL_CURRENCY_SYMBOLS - {sym}
    invented = any(other and other in message for other in foreign)
    return (0.0 if invented else 1.0), "no_invented_currency"


def is_actionable(message: str, case: EvalCase) -> tuple[float, str]:
    """1.0 iff the message contains an offer/ask/negotiation cue."""
    lowered = message.lower()
    hit = any(term in lowered for term in _ACTIONABLE_TERMS)
    return (1.0 if hit else 0.0), "is_actionable"


_SCORERS = (
    contains_engine_price,
    within_length,
    mentions_condition_when_present,
    no_invented_currency,
    is_actionable,
)


def aggregate_score(message: str, case: EvalCase) -> dict[str, object]:
    """Run all scorers and combine.

    Returns a dict with per-scorer scores, the mean ``aggregate`` (0..1),
    ``hard_pass`` (all hard scorers == 1.0) and ``passed`` (hard_pass AND
    aggregate >= 0.8).
    """
    scores: dict[str, float] = {}
    for scorer in _SCORERS:
        value, label = scorer(message, case)
        scores[label] = value

    aggregate = sum(scores.values()) / len(scores)
    hard_pass = all(scores[name] >= 1.0 for name in HARD_SCORERS)
    return {
        "scores": scores,
        "aggregate": aggregate,
        "hard_pass": hard_pass,
        "passed": hard_pass and aggregate >= 0.8,
    }
