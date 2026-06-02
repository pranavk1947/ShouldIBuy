"""DI container.

Mirrors loop-scribe's ``container.py``: a ``DeclarativeContainer`` with a
``Configuration`` provider plus ``Dependency()`` providers for the runtime
resources (the source chain and analysis repository) that are built and
overridden during the app lifespan. The ``AnalysisService`` is a ``Singleton``
wired from those providers.
"""

from __future__ import annotations

from typing import Any

from dependency_injector import containers
from dependency_injector import providers

from shouldibuy.service.analysis_service import AnalysisService


class Container(containers.DeclarativeContainer):
    """DI container for shouldibuy."""

    config = providers.Configuration()

    # Runtime dependencies — overridden during app startup.
    source_chain: providers.Dependency[Any] = providers.Dependency()
    analysis_repository: providers.Dependency[Any] = providers.Dependency()

    # Analysis service — uses the providers above.
    analysis_service = providers.Singleton(
        AnalysisService,
        source_chain=source_chain,
        repository=analysis_repository,
        stage_delay_seconds=config.PIPELINE.STAGE_DELAY_SECONDS,
    )
