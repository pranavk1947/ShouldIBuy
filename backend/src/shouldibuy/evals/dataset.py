"""Eval dataset for synthesis.

A list of ``EvalCase`` covering the market states (below/fair/above/well_above)
with and without condition flags. Each case carries a ``VerdictContext`` (the
synthesis input) and ``expectations`` consumed by the scorers.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from shouldibuy.llm.synthesis import VerdictContext


@dataclass
class EvalCase:
    """One synthesis eval case."""

    name: str
    context: VerdictContext
    expectations: dict[str, object] = field(default_factory=dict)


def _case(
    name: str,
    state: str,
    asking: float,
    low: float,
    high: float,
    currency: str = "USD",
    flags: list[str] | None = None,
) -> EvalCase:
    flags = flags or []
    return EvalCase(
        name=name,
        context=VerdictContext(
            state=state,
            asking=asking,
            low=low,
            high=high,
            currency=currency,
            condition_flags=flags,
        ),
        expectations={
            "max_length": 320,
            "expect_condition_mention": bool(flags),
            "currency": currency,
        },
    )


def dataset() -> list[EvalCase]:
    """Return the eval cases (~10 cases across states and flag combos)."""
    return [
        _case("below_clean", "below", 300.0, 400.0, 500.0),
        _case(
            "below_with_flags",
            "below",
            305.0,
            395.0,
            505.0,
            flags=["cosmetic: light scratches on back glass"],
        ),
        _case("fair_clean", "fair", 450.0, 400.0, 500.0),
        _case(
            "fair_with_flags",
            "fair",
            455.0,
            405.0,
            505.0,
            flags=["battery: no battery-health screenshot included"],
        ),
        _case("above_clean", "above", 560.0, 400.0, 500.0),
        _case(
            "above_with_flags",
            "above",
            565.0,
            405.0,
            505.0,
            flags=["cosmetic: scuffs on the frame"],
        ),
        _case("well_above_clean", "well_above", 700.0, 400.0, 500.0),
        _case(
            "well_above_with_flags",
            "well_above",
            720.0,
            410.0,
            510.0,
            flags=["cosmetic: cracked screen", "battery: unknown health"],
        ),
        _case("fair_gbp", "fair", 360.0, 320.0, 400.0, currency="GBP"),
        _case("above_eur", "above", 460.0, 320.0, 400.0, currency="EUR"),
    ]
