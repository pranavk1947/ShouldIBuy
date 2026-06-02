"""Server-Sent Events route for streaming analysis progress.

Uses a plain ``StreamingResponse`` (text/event-stream) backed by a per-analysis
``asyncio.Queue`` from the store. No third-party SSE dependency.
"""

from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from shouldibuy.core.store import STREAM_END, AnalysisStore, get_store

router = APIRouter(prefix="/api/analyses", tags=["sse"])


def _format_sse(event: dict) -> str:
    """Format one event as an SSE ``data:`` frame."""
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def _event_stream(
    analysis_id: str, store: AnalysisStore
) -> AsyncIterator[str]:
    queue = await store.subscribe(analysis_id)
    try:
        while True:
            item = await queue.get()
            if item is STREAM_END:
                break
            assert isinstance(item, dict)
            yield _format_sse(item)
    finally:
        await store.unsubscribe(analysis_id, queue)


@router.get("/{analysis_id}/events")
async def stream_events(
    analysis_id: str,
    store: Annotated[AnalysisStore, Depends(get_store)],
) -> StreamingResponse:
    """Stream analysis events as text/event-stream.

    Late subscribers replay buffered history first, then receive live events.
    """
    analysis = await store.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    return StreamingResponse(
        _event_stream(analysis_id, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
