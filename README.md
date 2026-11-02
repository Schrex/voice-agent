# Voice Agent — Field Request Assistant

Foremen call a dedicated number; an AI voice agent records their operational requests (trucks, equipment, material, labor) into a shared office queue, answers status questions, and transfers to the office line on request or emergency. Coordinators acknowledge, assign an owner, and resolve each request in a web dashboard.

Pilot: 30 days, 2–3 foremen, Schreiber Excavating.

## Stack

Twilio → ElevenLabs Agents (Claude Sonnet 5.5) → FastAPI (Python 3.12) → Supabase Postgres + Auth · React/TypeScript dashboard · Twilio SMS + Postmark alerts.

## Layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`app/`) and ElevenLabs agent-as-code (`agent/`) |
| `frontend/` | React/TS dashboard |
| `tests/` | Backend unit + integration tests, Playwright e2e, AC matrix |
| `docs/` | [Product spec](docs/product-specification.md) · [Architecture](docs/architecture.md) · [Task dependencies](docs/task-dependencies.md) · [ADRs](docs/adr/) |
| `GLOSSARY.md` | Domain vocabulary |
| `PROGRESS.md` | Build status |

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12 for you).

```bash
git clone https://github.com/Schrex/voice-agent.git
cd voice-agent/backend
uv sync
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/voice_agent
uv run alembic upgrade head        # schema
uv run python -m app.seed          # sample roster + jobs (seed/sample_roster.json); safe to re-run
uv run uvicorn app.main:app --reload
```

Needs a Postgres reachable at `DATABASE_URL` (Supabase local, or plain Postgres). Then `curl localhost:8000/healthz` returns `{"status":"ok","db":"ok"}` (503 if the database is unreachable).

Checks (the same ones CI runs on every PR), from `backend/`:

```bash
uv run ruff check . ../tests && uv run ruff format --check . ../tests
uv run mypy
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/voice_agent_test uv run pytest
```

Integration tests (`tests/integration/`) wipe and migrate the database named by `TEST_DATABASE_URL`; point it at a disposable database.
