"""FastAPI application + DI wiring.

Mirrors loop-scribe's ``app.py``: a lifespan builds the DI ``Container``, calls
``startup.build_*`` to construct concrete resources, overrides the container's
``Dependency`` providers, and stores the container + service on ``app.state``.
The controller pulls the service from the container and mounts its router.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shouldibuy import __version__
from shouldibuy.config.settings import get_settings
from shouldibuy.container import Container
from shouldibuy.controllers.analyses_controller import AnalysesController
from shouldibuy.startup import build_analysis_repository
from shouldibuy.startup import build_source_chain
from shouldibuy.utils.logging.log_config import setup_logging

setup_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire the DI container and mount controllers."""
    settings = get_settings()

    container = Container()
    container.config.from_dict(
        {"PIPELINE": {"STAGE_DELAY_SECONDS": settings.PIPELINE.STAGE_DELAY_SECONDS}}
    )
    app.state.container = container

    # --- Build resources ---
    source_chain = build_source_chain(settings)
    analysis_repository = build_analysis_repository(settings)

    # --- Wire DI container ---
    container.source_chain.override(source_chain)
    container.analysis_repository.override(analysis_repository)

    # --- Build service + mount controller ---
    service = container.analysis_service()
    app.state.analysis_service = service

    controller = AnalysesController(service)
    app.include_router(controller.router)

    logger.info("ShouldIBuy API started", version=__version__)
    yield
    logger.info("ShouldIBuy API shutting down")


def _build_cors_origins() -> list[str]:
    settings = get_settings()
    cors = getattr(settings, "CORS", None)
    origins = getattr(cors, "ORIGINS", None) if cors else None
    return list(origins) if origins else ["http://localhost:3000"]


app = FastAPI(
    title="ShouldIBuy API",
    version=__version__,
    description="Buyer-side 'is this a fair price?' analysis API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def main() -> None:
    settings = get_settings()
    port = int(os.environ.get("PORT", getattr(settings.SERVER, "PORT", 8000)))
    reload = os.environ.get("APP_ENV", "local") == "local"
    uvicorn.run("shouldibuy.app:app", host="0.0.0.0", port=port, reload=reload)


if __name__ == "__main__":
    main()
