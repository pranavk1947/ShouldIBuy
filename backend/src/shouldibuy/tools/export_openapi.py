"""Export the OpenAPI schema to a file.

Usage::

    python -m shouldibuy.tools.export_openapi openapi.json

The schema is generated from a fresh app instance with the routes mounted (the
controller is normally mounted in the lifespan, so we mount it here directly).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shouldibuy.app import app
from shouldibuy.config.settings import get_settings
from shouldibuy.container import Container
from shouldibuy.controllers.analyses_controller import AnalysesController
from shouldibuy.startup import build_analysis_repository
from shouldibuy.startup import build_source_chain


def _app_with_routes():
    settings = get_settings()
    container = Container()
    container.config.from_dict(
        {"PIPELINE": {"STAGE_DELAY_SECONDS": settings.PIPELINE.STAGE_DELAY_SECONDS}}
    )
    container.source_chain.override(build_source_chain(settings))
    container.analysis_repository.override(build_analysis_repository(settings))
    service = container.analysis_service()
    controller = AnalysesController(service)
    app.include_router(controller.router)
    return app


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(
            "usage: python -m shouldibuy.tools.export_openapi <path>",
            file=sys.stderr,
        )
        return 2
    out_path = Path(argv[0])
    schema = _app_with_routes().openapi()
    out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"wrote OpenAPI schema -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
