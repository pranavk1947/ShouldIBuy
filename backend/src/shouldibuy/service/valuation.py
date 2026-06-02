"""Valuation helpers — pure functions, no dependencies.

INVARIANT: every monetary figure surfaced to the user originates here, never
from an LLM. These functions are deterministic and unit-tested. Logic is
identical to the original ``pipeline/valuation.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

from shouldibuy.model.dtos import MarketState


def _sorted_pairs(
    values: Sequence[float], weights: Sequence[float]
) -> list[tuple[float, float]]:
    if len(values) != len(weights):
        raise ValueError("values and weights must be the same length")
    if not values:
        raise ValueError("values must be non-empty")
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")
    return sorted(zip(values, weights), key=lambda p: p[0])


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Return the weighted median of ``values``.

    The weighted median is the value where the cumulative weight first reaches
    half of the total weight. When the half-weight boundary falls exactly
    between two values, their unweighted average is returned.
    """
    pairs = _sorted_pairs(values, weights)
    total = sum(w for _, w in pairs)
    if total <= 0:
        raise ValueError("sum of weights must be positive")

    half = total / 2.0
    cumulative = 0.0
    for index, (value, weight) in enumerate(pairs):
        cumulative += weight
        if cumulative > half:
            return value
        if cumulative == half:
            # Boundary lands exactly between this value and the next.
            if index + 1 < len(pairs):
                return (value + pairs[index + 1][0]) / 2.0
            return value
    # Fallback (should be unreachable given total > 0).
    return pairs[-1][0]


def percentile_value(values: Sequence[float], pct: float) -> float:
    """Return the ``pct`` (0-100) percentile using linear interpolation.

    Matches NumPy's default ("linear") method so results are predictable.
    """
    if not values:
        raise ValueError("values must be non-empty")
    if not 0.0 <= pct <= 100.0:
        raise ValueError("pct must be within [0, 100]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def iqr(values: Sequence[float]) -> float:
    """Return the interquartile range (75th percentile minus 25th)."""
    return percentile_value(values, 75.0) - percentile_value(values, 25.0)


def percentile_of(value: float, values: Sequence[float]) -> int:
    """Return the percentile rank (0-100, rounded) of ``value`` among ``values``.

    Uses the "mean" definition: (count below + 0.5 * count equal) / n.
    """
    if not values:
        raise ValueError("values must be non-empty")
    n = len(values)
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    rank = (below + 0.5 * equal) / n
    return int(round(rank * 100))


def typical_range(values: Sequence[float]) -> tuple[float, float]:
    """Return the (25th, 75th) percentile range as a ``(low, high)`` tuple."""
    return percentile_value(values, 25.0), percentile_value(values, 75.0)


def classify_state(percentile: int) -> MarketState:
    """Map an asking-price percentile to a market state.

    - ``< 35``        -> below (a good deal)
    - ``35..65``      -> fair
    - ``66..85``      -> above
    - ``> 85``        -> well_above
    """
    if percentile < 0 or percentile > 100:
        return "unknown"
    if percentile < 35:
        return "below"
    if percentile <= 65:
        return "fair"
    if percentile <= 85:
        return "above"
    return "well_above"
