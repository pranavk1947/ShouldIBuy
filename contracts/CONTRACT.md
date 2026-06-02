# API & SSE Contract (source of truth for FE ⇄ BE)

The Pydantic models in `backend/src/shouldibuy/domain/` are the canonical definition.
This doc is the human-readable mirror both the backend and frontend MUST conform to.
`contracts/openapi.json` is generated from FastAPI; `frontend/src/types/api.d.ts` is generated from that.

## REST

### POST /api/analyses
Request:
```json
{ "url": "https://www.ebay.com/itm/...", "options": { "forceFresh": false } }
```
Headers: optional `Idempotency-Key: <string>`
Response `202`:
```json
{ "analysisId": "an_abc123", "status": "queued" }
```

### GET /api/analyses/{id}
Response `200` — the current snapshot (fields populate as the pipeline progresses):
```json
{
  "analysisId": "an_abc123",
  "status": "queued|extracting|comping|conditioning|synthesizing|done|degraded|failed",
  "listing": { ...ListingDTO } | null,
  "marketVerdict": { ...MarketVerdictDTO } | null,
  "condition": { ...ConditionDTO } | null,
  "verdict": { ...VerdictDTO } | null,
  "traceId": "..."
}
```

### GET /api/analyses/{id}/events  (Server-Sent Events)
`Content-Type: text/event-stream`. Each message is a single JSON object on the `data:` line,
discriminated by `type`. Event sequence for a typical analysis:

```
{ "type": "progress", "stage": "extracting", "message": "Reading the listing…" }
{ "type": "listing_parsed", "listing": ListingDTO }
{ "type": "progress", "stage": "comping", "message": "Finding comparable listings…" }
{ "type": "market_verdict", "marketVerdict": MarketVerdictDTO }
{ "type": "condition", "condition": ConditionDTO }
{ "type": "progress", "stage": "synthesizing", "message": "Writing your verdict…" }
{ "type": "verdict", "verdict": VerdictDTO }
{ "type": "done" }
```
Error path: `{ "type": "error", "message": "..." }` then `{ "type": "done" }`.

## DTOs

### ListingDTO
```json
{
  "title": "Apple iPhone 13 128GB Blue Unlocked",
  "category": "phones",
  "attributes": { "brand": "Apple", "model": "iPhone 13", "storage": "128GB", "conditionGrade": "Good" },
  "price": { "amount": 420, "currency": "USD" },
  "conditionClaim": "mint condition",
  "location": { "label": "Oakland, CA" },
  "images": ["https://.../0.jpg", "https://.../1.jpg"]
}
```

### MarketVerdictDTO
```json
{
  "state": "below|fair|above|well_above|unknown",
  "asking": { "amount": 420, "currency": "USD" },
  "percentile": 82,
  "typicalRange": { "low": 330, "high": 400, "currency": "USD" },
  "compCount": 23
}
```

### ConditionDTO
```json
{
  "flags": [
    { "kind": "damage", "detail": "hairline screen crack, top-left", "imageIndex": 1 }
  ],
  "mismatches": [
    { "claim": "mint condition", "evidence": "visible case wear", "imageIndex": 3 }
  ]
}
```

### VerdictDTO
```json
{
  "state": "below|fair|above|well_above|unknown",
  "headline": "Above typical — asking $420 sits at the 82nd percentile of 23 active listings.",
  "negotiationMessage": "Hi — noticed a small screen crack in photo 2. Comparable Good-condition units are asking $330–$400. Would you do $340?",
  "confidence": "high|medium|low|none"
}
```

## Notes / invariants
- All monetary numbers in `VerdictDTO`/`MarketVerdictDTO` come from the valuation engine, never from an LLM.
- `unknown` market state + `none` confidence is the graceful "can't say" outcome.
- The frontend renders progressively as events arrive; `GET /api/analyses/{id}` is the resume path if the stream drops.
