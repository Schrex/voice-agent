# Cloud sessions (claude.ai/code)

Run tickets in Anthropic-hosted sandboxes so work continues with the laptop off, several tickets at once.

## What the repo provides

- `.claude/settings.json` SessionStart hook → `scripts/cloud-setup.sh`. Runs only when `CLAUDE_CODE_REMOTE=true`.
- Setup: uv + Python 3.12, `uv sync` in `backend/`, `npm ci` in `frontend/` (each skipped until the folder has its manifest), `gh` CLI, local Postgres with `voice_agent` and `voice_agent_test` DBs.
- Exports `DATABASE_URL`, `TEST_DATABASE_URL` (`postgresql+psycopg://postgres:postgres@localhost:5432/...`), `TZ=America/New_York`, `APP_ENV=local`.
- Tests use this per-sandbox Postgres, never the cloud Supabase DB: parallel sessions sharing one DB would clobber each other's data and run unmerged migrations against a shared schema.
- Plain Postgres replaces Supabase local (it needs Docker, which cloud sessions don't have). Tests must read the DB URL from env, never hard-code the Supabase port.

## One-time environment setup (claude.ai/code → environment settings)

1. **Repo**: connect GitHub app to `Schrex/voice-agent`.
2. **Network access**: `Trusted` (package registries + GitHub), plus custom domains `*.supabase.co` and `api.supabase.com`. Add `api.elevenlabs.io` only for a session that runs `push.py` against a dev agent.
3. **Environment variables**:
   - No `GH_TOKEN`. The session proxy authenticates GitHub REST calls (`gh api repos/...`) as the account that connected GitHub to Claude. A PAT adds nothing: `gh issue` / `gh pr` use GraphQL, which cloud sessions block with or without a token. Don't add one. Sessions may still show a platform-provided `GH_TOKEN` that `gh auth status` reports as invalid; that is expected and harmless, since `gh api` calls work.
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`: from a **dev** Supabase project only. Used for Auth/JWT work (dashboard login, `/api` JWT verification), not for tests' database.
   - `SUPABASE_ACCESS_TOKEN` (Management API): only if a session must create projects or run migrations remotely. It is account-wide (it can delete prod), so prefer leaving it out and doing T02-style project setup from the laptop.
   - No staging/prod secrets (Supabase service keys, Twilio, Postmark, EL prod keys). Cloud sessions build and test against local Postgres and mocks only.
4. Setup script field: leave empty; the repo hook does the work and stays versioned.

## Running tickets in parallel

One session per ticket. Prompt for each:

> Work on issue #N. Follow AGENTS.md. Claim it first (`gh api -X POST repos/Schrex/voice-agent/issues/N/assignees -f 'assignees[]=<your-github-login>'`), then branch, implement with tests, and open a draft PR that says `Closes #N`. Use `gh api` REST calls or the session's GitHub tools, not `gh issue`/`gh pr` (blocked in cloud sessions); see `docs/agents/issue-tracker.md`.

- Pick only frontier tickets: open, `ready-for-agent`, no open blockers, no assignee (the **Frontier query** in `docs/agents/issue-tracker.md` lists them). Assignment is the lock; skip assigned tickets.
- Each session gets its own branch; merge order follows the issue blocker edges.
- Tickets touching the same files (e.g. two that both add Alembic migrations) run one after another, not in parallel: migration heads collide.
- `PROGRESS.md` edits go in the PR; expect small merge conflicts there and resolve on merge.
- `ready-for-human` tickets (e.g. #37: real phones, accounts) never go to cloud sessions.

## Limits

- No Docker, no real phone calls, no EL simulation tests against staging (layer 3 and 5 stay manual or on main-branch CI).
- Sandbox is discarded after the session; anything not pushed is lost.
