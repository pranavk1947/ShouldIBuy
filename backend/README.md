# ShouldIBuy — Backend

A buyer-side "is this a fair price?" API. Submit a used-item listing URL and get
a streamed analysis: extract → comps → condition → synthesize.

This is **M0** (a walking skeleton) plus scaffolding for **M1** (a data-source
adapter SDK + a real, tested valuation engine).

## Stack

- Python 3.12 target (runs on 3.10+), FastAPI, fully async, in-process.
- Pydantic v2 + pydantic-settings.
- SSE via a plain `StreamingResponse` reading from a per-analysis `asyncio.Queue`.
- In-memory analysis store behind an `AnalysisStore` Protocol (Postgres swaps in for M1).
- `Source` adapter SDK + an eBay Browse adapter skeleton with a golden fixture.

## Layout

```
src/shouldibuy/
  api/        FastAPI app, routes (POST/GET analyses, SSE), /healthz
  core/       config, store (+ event bus), id generation
  domain/     DTOs, SSE event union, enums (camelCase wire format)
  pipeline/   orchestrator (M0 staged run) + valuation engine (pure, tested)
  sources/    Source Protocol + eBay adapter + golden fixtures
  tools/      export_openapi
tests/
  unit/       valuation tests (deterministic)
  contract/   eBay adapter contract test (no network)
```

## Run locally

```bash
# install (editable) — uv recommended
uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"

# serve
uvicorn shouldibuy.api.main:app --reload --port 8000

# tests
pytest -q

# export the OpenAPI schema (FE codegen)
python -m shouldibuy.tools.export_openapi openapi.json
```

## API contract

- `POST /api/analyses` body `{"url": str, "options": {"forceFresh": bool} | null}`,
  optional `Idempotency-Key` header → `202 {"analysisId", "status": "queued"}`.
  Re-using an idempotency key within the process returns the same id.
- `GET /api/analyses/{id}` → snapshot
  `{analysisId, status, listing?, marketVerdict?, condition?, verdict?, traceId}`.
- `GET /api/analyses/{id}/events` → `text/event-stream`; each frame `data: <json>\n\n`.
  Event `type`s: `progress | listing_parsed | market_verdict | condition | verdict | error | done`.

Statuses: `queued | extracting | comping | conditioning | synthesizing | done | degraded | failed`.

### Invariant

All monetary figures in `MarketVerdictDTO` / `VerdictDTO` come from the valuation
engine (`pipeline/valuation.py`) — never from an LLM.

## Deploy

`Dockerfile` (python:3.12-slim + uv) and `fly.toml` (`shouldibuy-api`, always-on
so SSE streams aren't cut by cold starts) are provided.

## M1 TODOs

Grep for `# TODO(M1)`:
- Live eBay OAuth + Browse fetch (network path is stubbed, not called in tests).
- Comps source (sold listings) feeding the valuation engine.
- Postgres-backed `AnalysisStore` + Redis event bus.
- Real condition stage (image analysis + claim parsing).
