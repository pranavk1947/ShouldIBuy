# ShouldIBuy API (DES architecture)

Buyer-side "is this a fair price?" analysis API, refactored into the **DES
(Dependency-injected, Explicit, Structured)** house style used across Loop Health
services (see `loop-scribe`). Runtime behavior and the FE ⇄ BE SSE contract are
preserved exactly; only the internal structure changed.

## Layout

```
src/shouldibuy/
  app.py            FastAPI app + lifespan that builds the DI container,
                    calls startup.build_*, overrides providers, mounts the
                    controller, and stores app.state.
  startup.py        build_source_chain(settings), build_analysis_repository(settings)
                    — return concrete implementations.
  container.py      dependency-injector DeclarativeContainer: Configuration +
                    Dependency() providers (source_chain, analysis_repository)
                    + Singleton AnalysisService wired from them.
  config/           Dynaconf settings (get_settings) + properties/*.toml,
                    env selected by APP_ENV (default local), envvar_prefix=APP.
  controllers/      AnalysesController — a controller CLASS that registers its
                    REST + SSE routes in _register_routes, plus /healthz.
  service/          analysis_service.py (the staged M0 orchestrator) and
                    valuation.py (pure, deterministic valuation functions).
  integrations/
    sources/        Source Protocol (provider.py), EbayBrowseSource (ebay.py),
                    SourceFallbackChain (tenacity + pybreaker) + fixtures.
  repository/       AnalysisRepository Protocol + InMemoryAnalysisRepository,
                    which doubles as the per-analysis SSE event bus.
  model/            Pydantic DTOs (dtos.py), SSE event union (events.py),
                    internal Analysis dataclass (analysis.py).
  utils/            structlog logging (logging/log_config.py) and a no-op
                    `traced` tracing placeholder (observability/tracing.py).
  tools/            export_openapi.py
tests/
  unit/             valuation, repository, DTO aliasing.
  integration/      eBay adapter contract, end-to-end pipeline event sequence.
```

## DES conventions applied

- **Protocol over ABC** for all interfaces (`Source`, `AnalysisRepository`),
  `@runtime_checkable`. **Pydantic v2** at API/message boundaries; `@dataclass`
  for internal domain objects (`Analysis`, `NormalizedListing`, `Comp`).
- **Explicit DI** via `dependency-injector` wired in the app lifespan.
- **Config** via Dynaconf (`get_settings()`), `APP_ENV` overlays, `APP_*` env.
- **Logging** via structlog (`setup_logging()`); `structlog.get_logger(__name__)`.
- **Resilience** via a `SourceFallbackChain` (tenacity retry +
  per-source pybreaker circuit breaker) with `AllSourcesFailedError`.
- **Controller pattern**: route classes with `_register_routes`.

## Run

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m uvicorn shouldibuy.app:app --port 8000
# or, after `pip install .`:
shouldibuy
```

## Test

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src pytest                      # all
PYTHONPATH=src pytest -m "not integration" # unit only
```

## Roadmap markers

- `TODO(M1)`: live eBay fetch/OAuth, comps from a real source, Postgres/Redis
  repository, image-based condition analysis.
- `TODO(M3)`: OpenTelemetry wiring behind the no-op `traced` decorator.
