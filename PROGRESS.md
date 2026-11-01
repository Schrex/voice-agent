# Progress

Work is tracked as GitHub issues #1–#37 on Schrex/voice-agent (thin vertical slices, native "blocked by" edges; issue number = ticket number).
Frontier = open issues with no open blockers: the **Frontier query** in `docs/agents/issue-tracker.md`.
docs/task-dependencies.md is the original layer-based plan, superseded by the issues for build order.

| Current | Status | Notes |
|---|---|---|
| #1 Backend skeleton with health check and CI | done | PR #39; CI red-on-failing-test proven in run 41345092960 |
| #2 Database baseline with roster and jobs | done | Migration `0001` (foremen, foreman_phones, jobs, job_aliases); seed command; `/healthz` checks DB |
| #3 Staging environment, always on | code done; deploy deferred | `render.yaml`, `deploy-staging.yml`, Sentry init (`app/observability.py`), `.env.example`, `docs/staging.md`. Live deploy, uptime alert and Sentry screenshot need accounts (runbook) |

## Decisions log

- 2026-11-01: Product spec, architecture, task plan, ADRs 0001–0005 written.
- 2026-11-01: Spec broken into 37 thin-slice tickets (#1–#37) with per-ticket Definition of Done; #37 is ready-for-human.
- 2026-11-01 (#1): Backend managed with uv (`backend/pyproject.toml` + `uv.lock`); lint = ruff (check + format), type-check = mypy strict; pytest runs from `backend/` against root `tests/unit/`.
- 2026-11-01 (#2): "Local Supabase Postgres" = plain local Postgres in cloud sessions and CI (Supabase CLI needs Docker, unavailable there). Code only sees `DATABASE_URL` / `TEST_DATABASE_URL` (`postgresql+psycopg://…`), so Supabase local works the same on a laptop.
- 2026-11-01 (#2): DB stack: SQLAlchemy 2 (typed `Mapped` models in `app/db/models.py`, constraint naming convention) + psycopg 3 + Alembic (`backend/alembic.ini`, scripts in `app/db/migrations/`, revision ids `0001`, `0002`, …; generate with `uv run alembic revision --autogenerate --rev-id 000N -m "..."`, then review). `env.py` takes the URL from the Alembic config if set, else `DATABASE_URL`.
- 2026-11-01 (#2): DB session: `app/db/session.py` — `get_session()` is the FastAPI dependency (one Session per request); `new_session()` for scripts. Services take a `Session` argument and own `commit()`.
- 2026-11-01 (#2): Test DB pattern: I-tests live in `tests/integration/`; `conftest.py` wipes `public` in `TEST_DATABASE_URL` and runs `alembic upgrade head` once per run (fails if unset). `db_session` wraps each test in an outer transaction rolled back afterwards (`join_transaction_mode="create_savepoint"`, so code may commit); `client` is a TestClient with `get_session` overridden to `db_session`. CI runs a `postgres:16` service for them.
- 2026-11-01 (#2): `/healthz` runs `SELECT 1`: 200 `{"status":"ok","db":"ok"}`, else 503 `{"status":"error","db":"unreachable"}`.
- 2026-11-01 (#2): Seed: `uv run python -m app.seed [file]` loads JSON (default `backend/seed/sample_roster.json`, fictional 555 numbers). Upserts jobs by name and foremen by any of their phone numbers; adds missing aliases/phones; never deletes. `foreman_phones.e164` is unique and must match E.164 (`^\+[1-9][0-9]{1,14}$`); input normalization of other formats is not done.
- 2026-11-01 (#3): Host = Render (architecture allowed Render or Railway): Blueprint `render.yaml`, Starter plan (always on), `autoDeploy: false`; build with uv (`uv sync --locked --no-dev`), pre-deploy `alembic upgrade head`, health check `/healthz`.
- 2026-11-01 (#3): Deploy on merge = `deploy-staging.yml`, triggered by a successful CI `push` run on `main` (or manually); deploys that exact commit through the Render API and waits for `live`, then smoke-tests `/healthz`. GitHub environment `staging`: secret `RENDER_API_KEY`, vars `RENDER_STAGING_SERVICE_ID`, `STAGING_URL`.
- 2026-11-01 (#3): Sentry: `app/observability.init_sentry` runs at import of `app.main`, only when `SENTRY_DSN` is set; `environment` = `APP_ENV` (default `local`); no tracing, no PII. `python -m app.observability` sends a test exception. Settings live in `app/config.py` as plain functions; every variable is listed in root `.env.example`.

## Open items

- Office line behavior for overnight transfers (rings where? voicemail?).
- Overnight Overdue SMS: send immediately (current default) or hold until morning.
- Safety-lead approval of the emergency line.
