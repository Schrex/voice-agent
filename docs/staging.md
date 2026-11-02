# Staging runbook

Staging = one always-on Render web service (`render.yaml`) + its own Supabase project + Sentry + an external uptime monitor on `/healthz`. A merge to `main` deploys it: CI passes → `.github/workflows/deploy-staging.yml` asks Render to deploy that commit, waits for it to go live, then checks `/healthz`.

The code side is in the repo. The steps below need accounts and are done once by a person.

## 1. Supabase staging project

1. Create a project `voice-agent-staging` in region East US (N. Virginia), same as the Render service. Save the DB password in the password manager.
2. Project Settings → Database → Connection string → **Session pooler** (IPv4; Render has no IPv6 route to the direct host). Change the scheme to `postgresql+psycopg://`:
   `postgresql+psycopg://postgres.<ref>:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
   URL-encode special characters in the password.
3. Project Settings → API: copy the project URL and the `anon` public key (Render step 3.2). A new project signs tokens with asymmetric keys; the backend fetches their public half from the project URL, so it needs no secret. Only if the project still uses the legacy JWT secret, copy that too. Never copy the `service_role` key into Render's `VITE_*` vars.
4. Authentication → Providers → Email: enabled; turn off public sign-ups (staff accounts are created here by an admin: Authentication → Users → Add user). Add each new user's id to the `staff` table (seed file `staff` list, `python -m app.seed <file>` from the Render shell) or they are refused.
5. Don't run migrations by hand: every deploy runs `alembic upgrade head` (Render pre-deploy command).

## 2. Sentry

1. Create a Python/FastAPI project `voice-agent-backend`. Copy its DSN.
2. Alert rule: notify on every new issue (email to the team).

## 3. Render service

1. New → Blueprint → connect `Schrex/voice-agent`, branch `main`. Render reads `render.yaml` and creates `voice-agent-staging` (Starter plan: always on, no spin-down).
2. When prompted, set the secret env vars: `DATABASE_URL` (step 1), `SENTRY_DSN` (step 2), `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (step 1.3), and `SUPABASE_JWT_SECRET` only for a legacy-secret project (leave it empty otherwise). The backend also reads the project URL from `VITE_SUPABASE_URL`. `APP_ENV=staging` comes from the Blueprint.
3. Note the service id (`srv-…`, in the dashboard URL) and the public URL (`https://voice-agent-staging.onrender.com` or similar).
4. Account Settings → API Keys → create a key for GitHub Actions.

## 4. GitHub

Settings → Environments → create `staging`, then add:

| Kind | Name | Value |
|---|---|---|
| Secret | `RENDER_API_KEY` | Render API key (step 3.4) |
| Variable | `RENDER_STAGING_SERVICE_ID` | `srv-…` |
| Variable | `STAGING_URL` | public URL, no trailing slash |

Then Actions → **Deploy staging** → Run workflow (first deploy). After that, every merge to `main` with green CI deploys.

## 5. Uptime monitor

Any external monitor that can text within a minute (e.g. Better Stack, UptimeRobot paid plan for 30 s checks):

- HTTP check on `$STAGING_URL/healthz`, every 30 s, expect status 200 (it returns 503 when the DB is unreachable).
- Alert by SMS to the on-call phone after 1 failed check, and on recovery.

## 6. Verify (ticket #3 Definition of Done)

1. `curl -i $STAGING_URL/healthz` → `200 {"status":"ok","db":"ok"}`.
2. Merge any PR to `main` → link the **Deploy staging** run that went green.
3. Render → service → Suspend. Within 1 min the uptime monitor alerts (screenshot). Resume; recovery alert arrives.
4. Render → service → Shell: `.venv/bin/python -m app.observability` sends a test exception. Screenshot the Sentry issue (environment `staging`).
5. Secrets check: `git grep -nE "sk_|srv-|supabase.co|ingest.sentry.io"` finds only placeholders and test fakes.
