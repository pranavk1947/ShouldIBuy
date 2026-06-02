# ShouldIBuy

**Is this a fair price?** Paste a used-item listing URL (eBay, used phones to start) and get:
- where the asking price sits in the live market (percentile + typical range),
- condition red flags read from the photos (and claim↔photo mismatches),
- a ready-to-send negotiation message,
- an honest **confidence** level.

Results stream into the UI progressively over Server-Sent Events.

> This is a portfolio project engineered to demonstrate robust third-party **integration** design (pluggable `Source` adapter SDK), API **deprecation/migration** handling, an **async + observable** pipeline, **evals as CI gates**, and **agentic** adapter development.

## Architecture (one repo, two apps)
- `backend/` — Python 3.12 + FastAPI (async, in-process), Redis, Postgres, S3-compatible object store. Source adapters (eBay Browse, SerpAPI) behind a `Source` Protocol.
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
Milestone **M0 (walking skeleton)** + start of **M1**. The async→SSE→typed-boundary spine is in place; the orchestrator currently emits a staged demo sequence. The `Source` SDK and the eBay adapter skeleton (with golden fixtures + contract tests) are scaffolded. See `docs/MILESTONES.md`.
