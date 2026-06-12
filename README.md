# ShouldIBuy

**Is this a fair price?** Paste a used-item listing URL (eBay, used phones to start) and get:
- where the asking price sits in the live market (percentile + typical range),
- condition red flags and claim↔photo mismatches (staged stub today; vision analysis is the M2 roadmap),
- a ready-to-send negotiation message (LLM-worded, engine-numbered — guarded against hallucinated figures),
- an honest **confidence** level.

Results stream into the UI progressively over Server-Sent Events.

> This is a portfolio project engineered to demonstrate robust third-party **integration** design (pluggable `Source` adapter SDK), API **deprecation/migration** handling, an **async + observable** pipeline, **evals as CI gates**, and **agentic** adapter development.

## Architecture (one repo, two apps)
- `backend/` — Python 3.12 + FastAPI (async, in-process), Redis, Postgres, S3-compatible object store. Source adapters (eBay Browse — full listing source; SerpAPI/Google Shopping — comps-only fallback) behind a `Source` Protocol with capability flags, retry, and per-source circuit breakers.
- `frontend/` — Next.js (App Router), consuming the SSE stream and rendering the verdict card.
- `contracts/` — `openapi.json` generated from FastAPI → TypeScript types for the frontend (single source of truth).

See `docs/` and the design docs for the full HLD, design rationale, and implementation plan.

## Deploy
Both apps deploy to **Fly.io** (`shouldibuy-api`, `shouldibuy-web`) with managed Postgres + Redis. See `docs/adr/0001-deployment.md`.

## Quickstart (local)
```bash
just up        # start postgres, redis, minio (docker compose)
just dev       # run backend (:8000) + frontend (:3000)
just gen-types # regenerate TS types from the FastAPI OpenAPI schema
just test      # run backend + frontend tests
```

## Status
Milestone **M1 + AI layer**. Working today:
- **Pipeline** — `POST /api/analyses` → SSE stream (`listing_parsed` → `market_verdict` → `condition` → `verdict` → `done`), resumable via `GET`.
- **Integrations** — eBay Browse adapter (OAuth2 client-credentials with cached tokens, `getItem` + comp search) and a SerpAPI/Google Shopping comps-only fallback adapter, both behind the `Source` Protocol. Comp gathering degrades by capability: primary source → fallback source → bundled golden fixtures, so the full pipeline runs offline with zero credentials.
- **AI synthesis** — an LLM words the negotiation message; the valuation engine owns every number. A guard rejects any output missing required engine figures or containing foreign currency symbols and falls back to a deterministic template.
- **Evals as CI gates** — `pytest -m eval` (11 synthesis evals) runs in CI; LangSmith tracing/evals activate when keys are present.
- **Not real yet** — the condition stage is a static stub (`TODO(M2)`: vision-based photo analysis).

Verified locally: ruff + mypy clean, 81 tests + 11 evals passing, frontend build + tests green. See `docs/MILESTONES.md`.
