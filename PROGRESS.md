# Progress

Work is tracked as GitHub issues #1–#37 on Schrex/voice-agent (thin vertical slices, native "blocked by" edges; issue number = ticket number).
Frontier = open issues with no open blockers: the **Frontier query** in `docs/agents/issue-tracker.md`.
docs/task-dependencies.md is the original layer-based plan, superseded by the issues for build order.

| Current | Status | Notes |
|---|---|---|
| #1 Backend skeleton with health check and CI | done | PR #39; CI red-on-failing-test proven in run 41345092960 |
| #2 Database baseline with roster and jobs | done | Migration `0001` (foremen, foreman_phones, jobs, job_aliases); seed command; `/healthz` checks DB |
| #4 Call-start check: rostered vs unrostered | done (I-tests); S/L deferred | Migration `0002` (calls); `POST /hooks/call-start`; synthetic EL fixtures in `tests/fixtures/elevenlabs/` |

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
- 2026-11-01 (#4): `POST /hooks/call-start` auth: `X-Hook-Secret` compared in constant time with env `HOOK_SECRET`; unset → every request 401 (fails closed). Checked in a dependency, so a bad secret is 401 before the body is validated.
- 2026-11-01 (#4): Call-start response (EL `conversation_initiation_client_data`) dynamic variables: `rejected` (bool), `foreman_first_name`, `jobs` (all active Job names, sorted, joined with "; "), `now_local` (America/New_York, e.g. "Sunday, November 1, 2026, 3:04 PM", `app/domain/local_time.py`). Unrostered: same keys empty, `rejected: true`, plus `conversation_config_override.agent.first_message` = spec J8 line with env `OFFICE_MAIN_NUMBER` inserted as written (unset → error).
- 2026-11-01 (#4): `calls` (`0002`): conversation_id unique, call_sid indexed, caller_e164, foreman_id nullable, started_at, outcome (A§5 values, non-native CHECK). Insert is `ON CONFLICT (conversation_id) DO NOTHING`; the first delivery binds the conversation and repeats reuse that row (never rebind). Rostered calls start with outcome null; unrostered get `rejected`. `conversation_id` is required in the payload (422 if absent).
- 2026-11-01 (#4): Clock: `app/clock.py` `get_clock` dependency returns a `() -> datetime` (UTC); I-tests override it to freeze time.

## Open items

- Office line behavior for overnight transfers (rings where? voicemail?).
- Overnight Overdue SMS: send immediately (current default) or hold until morning.
- Safety-lead approval of the emergency line.
