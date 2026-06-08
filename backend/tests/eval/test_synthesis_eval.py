"""Hermetic synthesis eval GATE.

Runs the offline ``DeterministicProvider`` through ``write_negotiation_message``
for every ``EvalCase`` and asserts each passes the scorer threshold (all hard
scorers true AND aggregate >= 0.8). This proves synthesis output quality with no
network — it runs in CI.
"""

from __future__ import annotations

import pytest

from shouldibuy.evals.dataset import dataset
from shouldibuy.evals.scorers import aggregate_score
from shouldibuy.llm.provider import DeterministicProvider
from shouldibuy.llm.synthesis import write_negotiation_message

pytestmark = pytest.mark.eval

_THRESHOLD = 0.8


@pytest.mark.parametrize("case", dataset(), ids=lambda c: c.name)
async def test_synthesis_case_passes_gate(case) -> None:
    provider = DeterministicProvider()
    message = await write_negotiation_message(provider, verdict_context=case.context)

    result = aggregate_score(message, case)
    assert result["hard_pass"], (
        f"{case.name}: hard scorers failed -> {result['scores']} :: {message!r}"
    )
    assert result["aggregate"] >= _THRESHOLD, (
        f"{case.name}: aggregate {result['aggregate']:.2f} < {_THRESHOLD} "
        f":: {result['scores']} :: {message!r}"
    )
    assert result["passed"], f"{case.name}: did not pass :: {message!r}"


async def test_dataset_covers_all_states() -> None:
    states = {case.context.state for case in dataset()}
    assert {"below", "fair", "above", "well_above"} <= states
    # At least some cases carry condition flags and some do not.
    with_flags = [c for c in dataset() if c.context.condition_flags]
    without_flags = [c for c in dataset() if not c.context.condition_flags]
    assert with_flags and without_flags
