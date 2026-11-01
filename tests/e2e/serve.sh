#!/usr/bin/env bash
# Backend for the Playwright specs: migrates and seeds E2E_DATABASE_URL, then serves the API and
# the built dashboard (frontend/dist) on E2E_PORT. Started by frontend/playwright.config.ts.
set -euo pipefail

: "${E2E_DATABASE_URL:?E2E_DATABASE_URL must name a disposable Postgres database}"
: "${E2E_PORT:=8765}"
: "${SUPABASE_JWT_SECRET:?}"

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/../../backend"

export DATABASE_URL="$E2E_DATABASE_URL"
export FRONTEND_DIST="$here/../../frontend/dist"
uv run alembic upgrade head
uv run python -m app.seed "$here/seed.json"
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$E2E_PORT"
