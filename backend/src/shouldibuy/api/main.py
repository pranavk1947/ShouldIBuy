"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shouldibuy import __version__
from shouldibuy.api import analyses, sse
from shouldibuy.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ShouldIBuy API",
        version=__version__,
        description="Buyer-side 'is this a fair price?' analysis API.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        # Expose nothing special; SSE works over a normal GET.
    )

    app.include_router(analyses.router)
    app.include_router(sse.router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
