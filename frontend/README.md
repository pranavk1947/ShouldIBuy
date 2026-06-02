# ShouldIBuy — Web (frontend)

Buyer-side "is this a fair price?" web app. Paste a used-item listing URL; the
backend analyzes it and streams results over Server-Sent Events, and this UI
renders a verdict card that fills in progressively.

This is **M0**, a walking skeleton: real Next.js (App Router, TypeScript) code,
hand-written DTO types, a pure tested SSE reducer, and a progressive verdict card.

## Stack

- Next.js 14 (App Router) + React 18 + TypeScript
- Plain CSS (single accent, no Tailwind)
- Vitest + Testing Library for unit tests
- `output: "standalone"` for a small Docker image; Fly config included

## Getting started

```bash
npm install
npm run dev          # http://localhost:3000
```

Set the backend origin (defaults to `http://localhost:8000`):

```bash
export NEXT_PUBLIC_API_URL=http://localhost:8000
```

## How it talks to the backend

- `POST /api/analyses` `{ url, options?: { forceFresh } }` (+ optional
  `Idempotency-Key`) → `202 { analysisId, status: "queued" }`. Goes through the
  Next.js rewrite proxy (`/api/*` → `${NEXT_PUBLIC_API_URL}/api/*`).
- `GET /api/analyses/{id}` → snapshot (resume path).
- `GET /api/analyses/{id}/events` → SSE. **Hits the FastAPI origin directly**
  via `NEXT_PUBLIC_API_URL`, not the rewrite (rewrites buffer streams). Parsed
  with `fetch()` + a `ReadableStream` reader (so we can send the
  `Idempotency-Key` header) — **not** `EventSource`.

## Architecture notes

- `src/lib/types.ts` — hand-written DTO + SSE event types (the discriminated
  union is keyed on `type`). _M1: replace with generated `src/types/api.d.ts`._
- `src/lib/sse.ts` — typed SSE stream parser over `fetch`.
- `src/lib/sseReducer.ts` — **pure** `(state, event) => state` reducer. This is
  the one piece exercising real logic in M0 and is unit-tested.
- `src/components/AnalyzePanel.tsx` — kicks off the POST, opens the stream,
  dispatches events into the reducer.
- `src/components/VerdictCard.tsx` — progressive card: skeleton → listing →
  market bar → condition flags → verdict + negotiation + confidence, colored by
  verdict state. The unknown/none state renders gracefully.

## Scripts

```bash
npm run dev      # dev server
npm run build    # production build (standalone)
npm run start    # run the production build
npm run lint     # next lint
npm run test     # vitest run
npm run gen:api  # (M1) regenerate types from backend OpenAPI
```

## Docker / Fly

```bash
docker build -t shouldibuy-web .
docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://host.docker.internal:8000 shouldibuy-web
# fly deploy   # uses fly.toml (app = "shouldibuy-web", internal_port 3000)
```

## TODOs (M1)

- Swap hand-written DTOs for generated `src/types/api.d.ts` via
  `openapi-typescript`.
- Point example chips at real backend fixture listings.
- Wire the snapshot/resume path (`getSnapshot`) for reconnects.
