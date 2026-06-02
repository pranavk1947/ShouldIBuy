# ADR 0001 — Deployment topology

**Status:** Accepted · **Date:** 2026-06

## Context
ShouldIBuy is one repo with two deployables: a Next.js frontend and a FastAPI backend.
The backend's v1 design deliberately has **no job queue** — `POST /analyses` returns `202`
immediately and the work continues **in-process**, streaming to the browser over a
**long-lived SSE** connection.

## Decision
Deploy **both apps to Fly.io** as two separate apps: `shouldibuy-api` and `shouldibuy-web`,
with managed **Postgres** and **Redis**, plus an S3-compatible object store (Tigris/MinIO).

## Why not serverless (e.g., Vercel for the backend)?
The in-process, long-running design conflicts with serverless execution:
- Function timeouts (Vercel Hobby 10s / Pro 60s) are shorter than a streamed analysis + open SSE.
- SSE idle timeout (~30s) and per-connection billing make long streams awkward.
- Background work that outlives the HTTP response is killed; serverless requires an external
  queue + worker — exactly the complexity we deferred until load justifies it.

So **platform choice is coupled to the no-queue decision**. Going serverless would mean
reintroducing a queue (e.g., Upstash + worker) and reshaping the pipeline — a future evolution,
not v1.

## Why two Fly apps instead of one container?
- Independent scaling (API is CPU-bound LLM/image work + long-lived connections; web is light).
- Independent rollback and separate secret surfaces.
- Avoids a fragile multi-process container.

## Consequences
- Frontend *could* alternatively live on Vercel (great DX) while the API stays on Fly — kept as a
  documented option; v1 standardizes on all-Fly for single-platform ops.
- Apps run **always-on** (no scale-to-zero) so the public demo never cold-starts.
- Trade: a server restart/deploy drops in-flight analyses; mitigated by persisting partials and
  using `GET /analyses/{id}` as the resume path.
