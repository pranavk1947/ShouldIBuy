# Milestones

- **M0 — Walking skeleton** ✅ (this drop)
  POST /analyses → in-process async → SSE → progressively-revealed verdict card.
  Domain models incl. the SSE event union; OpenAPI→TS type generation; both CI workflows;
  Dockerfiles + fly.toml for both apps. Orchestrator emits a staged demo sequence.
- **M1 — eBay adapter + valuation** 🚧 (scaffolded)
  `Source` Protocol + eBay Browse adapter skeleton (OAuth client-credentials) + golden fixtures
  + contract tests. Canonicalization + weighted median/IQR percentile valuation. Postgres + Alembic
  persistence; Redis idempotency + rate limiter.
- **M2 — SerpAPI + condition + synthesis** ⏳
  Second adapter; vision condition flags + claim↔photo mismatch; LLM synthesis (numbers engine-injected);
  LangSmith tracing.
- **M3 — confidence + observability + agent harness** ⏳
  Confidence model; OpenTelemetry dashboards correlated with LangSmith; eval gate; agent that
  scaffolds a new adapter, gated by contract tests.

See the design doc, HLD, and implementation plan for full rationale.
