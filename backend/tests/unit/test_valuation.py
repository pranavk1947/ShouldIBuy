"""Deterministic unit tests for the valuation engine."""

from __future__ import annotations

import pytest

from shouldibuy.pipeline import valuation


def test_percentile_value_linear_interpolation() -> None:
    values = [10, 20, 30, 40]
    # 25th pctile of 4 points: rank = 0.25 * 3 = 0.75 -> 10 + 0.75*10 = 17.5
    assert valuation.percentile_value(values, 25) == pytest.approx(17.5)
    # 75th: rank = 2.25 -> 30 + 0.25*10 = 32.5
    assert valuation.percentile_value(values, 75) == pytest.approx(32.5)
    assert valuation.percentile_value(values, 0) == 10
    assert valuation.percentile_value(values, 100) == 40


def test_percentile_value_single_element() -> None:
    assert valuation.percentile_value([42], 13) == 42


def test_iqr() -> None:
    assert valuation.iqr([10, 20, 30, 40]) == pytest.approx(15.0)


def test_typical_range() -> None:
    low, high = valuation.typical_range([10, 20, 30, 40])
    assert low == pytest.approx(17.5)
    assert high == pytest.approx(32.5)


def test_weighted_median_equal_weights_odd() -> None:
    assert valuation.weighted_median([1, 2, 3], [1, 1, 1]) == 2


def test_weighted_median_equal_weights_even_boundary() -> None:
    # Total weight 4, half 2; cumulative reaches exactly 2 at value 2 -> avg(2,3)
    assert valuation.weighted_median([1, 2, 3, 4], [1, 1, 1, 1]) == pytest.approx(2.5)


def test_weighted_median_skewed_weights() -> None:
    # The heavily-weighted value dominates the median.
    result = valuation.weighted_median([10, 20, 30], [1, 1, 10])
    assert result == 30


def test_weighted_median_validation() -> None:
    with pytest.raises(ValueError):
        valuation.weighted_median([1, 2], [1])  # length mismatch
    with pytest.raises(ValueError):
        valuation.weighted_median([], [])  # empty
    with pytest.raises(ValueError):
        valuation.weighted_median([1], [0])  # zero total weight
    with pytest.raises(ValueError):
        valuation.weighted_median([1], [-1])  # negative weight


def test_percentile_of_basic() -> None:
    values = [100, 200, 300, 400, 500]
    # 300 has 2 below, 1 equal -> (2 + 0.5)/5 = 0.5 -> 50
    assert valuation.percentile_of(300, values) == 50
    # below all
    assert valuation.percentile_of(50, values) == 0
    # above all -> (5 below)/5 = 100
    assert valuation.percentile_of(600, values) == 100


def test_percentile_of_empty_raises() -> None:
    with pytest.raises(ValueError):
        valuation.percentile_of(1, [])


@pytest.mark.parametrize(
    "pct,expected",
    [
        (0, "below"),
        (34, "below"),
        (35, "fair"),
        (50, "fair"),
        (65, "fair"),
        (66, "above"),
        (85, "above"),
        (86, "well_above"),
        (100, "well_above"),
        (-1, "unknown"),
        (101, "unknown"),
    ],
)
def test_classify_state(pct: int, expected: str) -> None:
    assert valuation.classify_state(pct) == expected


def test_engine_invariant_numbers_are_real() -> None:
    """End-to-end-ish: the M0 comp list yields a fair classification for $419.99."""
    comps = [349, 369, 379, 389, 399, 405, 410, 425, 430, 449, 469]
    pct = valuation.percentile_of(419.99, comps)
    low, high = valuation.typical_range(comps)
    state = valuation.classify_state(pct)
    assert low < 419.99 < high
    assert state in {"fair", "above"}
