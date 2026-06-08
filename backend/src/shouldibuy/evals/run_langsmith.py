"""Manual LangSmith eval runner (NOT run in CI).

Builds/loads a LangSmith dataset from ``evals.dataset`` and runs
``langsmith.evaluate`` over the configured ``LLMProvider`` using the pure
scorers in ``evals.scorers``. Requires ``LANGSMITH_API_KEY`` and ``LLM_API_KEY``
(or any configured provider key) and errors clearly when they are missing.

Run with::

    PYTHONPATH=src python3 -m shouldibuy.evals.run_langsmith
"""

from __future__ import annotations

import asyncio
import os
import sys

from shouldibuy.config.settings import get_settings
from shouldibuy.evals.dataset import EvalCase
from shouldibuy.evals.dataset import dataset
from shouldibuy.evals.scorers import HARD_SCORERS
from shouldibuy.evals.scorers import aggregate_score
from shouldibuy.llm.provider import build_llm_provider
from shouldibuy.llm.synthesis import VerdictContext
from shouldibuy.llm.synthesis import write_negotiation_message

_DATASET_NAME = "shouldibuy-synthesis"


def _require_keys() -> None:
    missing = [
        key for key in ("LANGSMITH_API_KEY", "LLM_API_KEY") if not os.getenv(key)
    ]
    if missing:
        raise SystemExit(
            "Missing required environment variables for the LangSmith run: "
            + ", ".join(missing)
            + ". This runner is manual (not CI) and needs live keys."
        )


def _case_by_name() -> dict[str, EvalCase]:
    return {case.name: case for case in dataset()}


def _context_from_inputs(inputs: dict[str, object]) -> VerdictContext:
    raw_flags = inputs.get("conditionFlags", [])
    flags = [str(f) for f in raw_flags] if isinstance(raw_flags, list) else []
    return VerdictContext(
        state=str(inputs["state"]),
        asking=float(inputs["asking"]),  # type: ignore[arg-type]
        low=float(inputs["low"]),  # type: ignore[arg-type]
        high=float(inputs["high"]),  # type: ignore[arg-type]
        currency=str(inputs["currency"]),
        condition_flags=flags,
    )


def main() -> int:
    """Build the dataset and run ``langsmith.evaluate``."""
    _require_keys()

    try:
        from langsmith import Client
        from langsmith import evaluate
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "langsmith is not installed; `pip install langsmith` to run evals."
        ) from exc

    settings = get_settings()
    provider = build_llm_provider(settings)
    cases = _case_by_name()

    client = Client()
    if not client.has_dataset(dataset_name=_DATASET_NAME):
        ls_dataset = client.create_dataset(dataset_name=_DATASET_NAME)
        for case in cases.values():
            client.create_example(
                dataset_id=ls_dataset.id,
                inputs={
                    "name": case.name,
                    "state": case.context.state,
                    "asking": case.context.asking,
                    "low": case.context.low,
                    "high": case.context.high,
                    "currency": case.context.currency,
                    "conditionFlags": case.context.condition_flags,
                },
                outputs={},
            )

    def target(inputs: dict[str, object]) -> dict[str, str]:
        context = _context_from_inputs(inputs)
        provider_local = provider
        message = asyncio.run(
            write_negotiation_message(provider_local, verdict_context=context)
        )
        return {"message": message}

    def make_scorer(label: str):  # noqa: ANN202 - LangSmith evaluator factory
        def _scorer(run: object, example: object) -> dict[str, object]:
            outputs = getattr(run, "outputs", {}) or {}
            message = str(outputs.get("message", ""))
            inputs = getattr(example, "inputs", {}) or {}
            name = str(inputs.get("name", ""))
            case = cases.get(name)
            if case is None:
                case = EvalCase(name=name, context=_context_from_inputs(inputs))
            result = aggregate_score(message, case)
            if label == "aggregate":
                value = float(result["aggregate"])  # type: ignore[arg-type]
            elif label == "passed":
                value = 1.0 if result["passed"] else 0.0
            else:
                scores: dict[str, float] = result["scores"]  # type: ignore[assignment]
                value = float(scores.get(label, 0.0))
            return {"key": label, "score": value}

        _scorer.__name__ = f"score_{label}"
        return _scorer

    evaluators = [make_scorer(name) for name in (*HARD_SCORERS, "aggregate", "passed")]

    results = evaluate(
        target,
        data=_DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix="synthesis",
    )
    print(f"LangSmith evaluation complete: {results}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
