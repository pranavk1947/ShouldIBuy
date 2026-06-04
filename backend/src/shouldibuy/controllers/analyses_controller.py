"""Analyses controller — REST + SSE.

Per the python-patterns house style this is a controller CLASS that registers
its routes onto an ``APIRouter`` in ``_register_routes``. The controller holds
the ``AnalysisService`` (pulled from the DI container in ``app.py``) and stays
thin: validation, status codes, and serialization only.

The SSE contract is preserved EXACTLY (event types and camelCase DTO fields).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException
from fastapi import Response
from fastapi import status
from fastapi.responses import StreamingResponse

from shouldibuy.model.dtos import AnalysisSnapshot
from shouldibuy.model.dtos import CreateAnalysisRequest
from shouldibuy.model.dtos import CreateAnalysisResponse
from shouldibuy.repository.analysis_repository import STREAM_END
from shouldibuy.service.analysis_service import AnalysisService

logger = structlog.get_logger(__name__)


def _format_sse(event: dict) -> str:
    """Format one event as an SSE ``data:`` frame."""
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


class AnalysesController:
    """Controller for the ``/api/analyses`` resource (REST + SSE) and health."""

    def __init__(self, service: AnalysisService) -> None:
        self._service = service
        self.router = APIRouter()
        self._register_routes(self.router)

    def _register_routes(self, router: APIRouter) -> None:
        router.add_api_route(
            "/healthz",
            self.healthz,
            methods=["GET"],
            tags=["meta"],
        )
        router.add_api_route(
            "/api/analyses",
            self.create_analysis,
            methods=["POST"],
            response_model=CreateAnalysisResponse,
            status_code=status.HTTP_202_ACCEPTED,
            tags=["analyses"],
        )
        router.add_api_route(
            "/api/analyses/{analysis_id}",
            self.get_analysis,
            methods=["GET"],
            response_model=AnalysisSnapshot,
            tags=["analyses"],
        )
        router.add_api_route(
            "/api/analyses/{analysis_id}/events",
            self.stream_events,
            methods=["GET"],
            tags=["sse"],
        )

    async def healthz(self) -> dict[str, str]:
        from shouldibuy import __version__

        return {"status": "ok", "version": __version__}

    async def create_analysis(
        self,
        body: CreateAnalysisRequest,
        response: Response,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateAnalysisResponse:
        """Create an analysis and kick off the in-process pipeline (202)."""
        if not body.url.strip():
            raise HTTPException(status_code=422, detail="url must not be empty")

        analysis_id = await self._service.create_analysis(
            body.url, idempotency_key=idempotency_key
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return CreateAnalysisResponse(analysis_id=analysis_id, status="queued")

    async def get_analysis(self, analysis_id: str) -> AnalysisSnapshot:
        """Return the current snapshot for an analysis (resume path)."""
        analysis = await self._service.get_analysis(analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        return analysis.to_snapshot()

    async def stream_events(self, analysis_id: str) -> StreamingResponse:
        """Stream analysis events as text/event-stream.

        Late subscribers replay buffered history first, then receive live events.
        """
        analysis = await self._service.get_analysis(analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="analysis not found")

        repo = self._service.repository

        async def _event_stream() -> AsyncIterator[str]:
            queue = await repo.subscribe(analysis_id)
            try:
                while True:
                    item = await queue.get()
                    if item is STREAM_END:
                        break
                    assert isinstance(item, dict)
                    yield _format_sse(item)
            finally:
                await repo.unsubscribe(analysis_id, queue)

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
            },
        )
