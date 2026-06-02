# ShouldIBuy task runner. Install `just`: https://github.com/casey/just

set dotenv-load := true

# List recipes
default:
    @just --list

# Start local infra (postgres, redis, minio)
up:
    docker compose up -d postgres redis minio

# Stop local infra
down:
    docker compose down

# Run backend + frontend together
dev:
    #!/usr/bin/env bash
    trap 'kill 0' EXIT
    just dev-be & just dev-fe & wait

# Backend dev server (:8000)
dev-be:
    cd backend && uv run uvicorn shouldibuy.api.main:app --reload --port 8000

# Frontend dev server (:3000)
dev-fe:
    cd frontend && pnpm dev

# Regenerate OpenAPI + TS types
gen-types:
    cd backend && uv run python -m shouldibuy.tools.export_openapi ../contracts/openapi.json
    cd frontend && pnpm exec openapi-typescript ../contracts/openapi.json -o src/types/api.d.ts

# Run all tests
test: test-be test-fe

test-be:
    cd backend && uv run pytest -q

test-fe:
    cd frontend && pnpm test

# Lint + typecheck everything
lint:
    cd backend && uv run ruff check . && uv run mypy src
    cd frontend && pnpm lint && pnpm exec tsc --noEmit
