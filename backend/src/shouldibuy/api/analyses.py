"""Analysis HTTP routes: create + snapshot."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from shouldibuy.core.ids import new_analysis_id, new_trace_id
from shouldibuy.core.store import AnalysisStore, get_store
from shouldibuy.domain.models import (
    AnalysisSnapshot,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
)
from shouldibuy.pipeline.orchestrator import make_analysis, run_analysis

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

# Track background tasks so they aren't garbage-collected mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


@router.post("", response_model=CreateAnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    body: CreateAnalysisRequest,
    response: Response,
    store: Annotated[AnalysisStore, Depends(get_store)],
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
) -> CreateAnalysisResponse:
    """Create an analysis and kick off the in-process pipeline.

    Returns 202 immediately. Re-using an ``Idempotency-Key`` within the process
    returns the same analysisId without starting a second run.
    """
    if not body.url.strip():
        raise HTTPException(status_code=422, detail="url must not be empty")

    if idempotency_key:
        existing = await store.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            response.status_code = status.HTTP_202_ACCEPTED
            return CreateAnalysisResponse(analysisId=existing, status="queued")

    analysis_id = new_analysis_id()
    trace_id = new_trace_id()
    analysis = make_analysis(analysis_id, trace_id)
    await store.create(analysis)

    if idempotency_key:
        await store.set_idempotency_key(idempotency_key, analysis_id)

    task = asyncio.create_task(run_analysis(analysis_id, body.url, store))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return CreateAnalysisResponse(analysisId=analysis_id, status="queued")


@router.get("/{analysis_id}", response_model=AnalysisSnapshot)
async def get_analysis(
    analysis_id: str,
    store: Annotated[AnalysisStore, Depends(get_store)],
) -> AnalysisSnapshot:
    """Return the current snapshot for an analysis (resume path)."""
    analysis = await store.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return analysis.to_snapshot()
