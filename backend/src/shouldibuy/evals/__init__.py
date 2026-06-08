"""Eval harness for the synthesis layer.

Importable by tests (the hermetic pytest gate) and by the manual
``run_langsmith`` runner. Provides a dataset of synthesis inputs + expectations
and pure scorer functions that judge the produced negotiation message.
"""

from __future__ import annotations

from shouldibuy.evals.dataset import EvalCase
from shouldibuy.evals.dataset import dataset
from shouldibuy.evals.scorers import aggregate_score

__all__ = ["EvalCase", "aggregate_score", "dataset"]
