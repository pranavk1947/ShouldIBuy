# 5-minute demo (zero credentials required)

The entire pipeline runs offline on golden fixtures — by design, not as a hack.
The live/fixture seam is the same code path an interviewer would inspect.

```bash
# 1. Boot (no .env needed)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m uvicorn shouldibuy.app:app --port 8000

# 2. Create an analysis
curl -s -X POST localhost:8000/api/analyses \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.ebay.com/itm/256789012345"}'
# -> {"analysisId":"an_…","status":"queued"}

# 3. Watch it stream (SSE)
curl -N localhost:8000/api/analyses/<analysisId>/events
# -> progress → listing_parsed → market_verdict → condition → verdict → done

# 4. Resume path (same data, no stream)
curl -s localhost:8000/api/analyses/<analysisId>

# 5. The proof: tests + eval gate
PYTHONPATH=src .venv/bin/python -m pytest -q          # 81 passed
PYTHONPATH=src .venv/bin/python -m pytest -q -m eval  # 11 passed
```

## Going live (10-minute key setup)

| Capability | Keys | Where |
|---|---|---|
| Live eBay listing + comps | `APP_EBAY__CLIENT_ID`, `APP_EBAY__CLIENT_SECRET` | developer.ebay.com → create app → client credentials |
| Fallback comps (Google Shopping) | `APP_SERPAPI__API_KEY` | serpapi.com → free tier, 100 searches/mo |
| LLM-worded negotiation message | `LLM_API_KEY` (+ optional `LLM_MODEL_SYNTHESIZE`) | any OpenAI-compatible provider |
| Tracing + hosted evals | `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | smith.langchain.com |

Each key unlocks its layer independently; everything else keeps running on
fixtures/deterministic providers. No key is load-bearing.
