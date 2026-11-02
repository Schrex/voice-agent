#!/usr/bin/env bash
# Bootstraps a Claude Code cloud session (claude.ai/code): Python 3.12 + uv,
# backend/frontend deps, and a local Postgres standing in for Supabase local
# (no Docker in cloud sessions). Runs from the SessionStart hook; no-op on laptops.
# Idempotent; never fails the session — problems are printed for the agent to see.

set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 0

log() { echo "[cloud-setup] $*"; }
warn() { echo "[cloud-setup] WARN: $*" >&2; }
export_env() {
  # Persist for every later Bash call in this session.
  [ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export $1=\"$2\"" >> "$CLAUDE_ENV_FILE"
  export "$1=$2"
}

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && SUDO="sudo"
# Run a command as the postgres OS user. Cloud sessions run as root, where SUDO is
# empty, so "$SUDO -u postgres" would not work there.
as_pg() {
  if [ "$(id -u)" -eq 0 ]; then runuser -u postgres -- "$@"; else sudo -u postgres "$@"; fi
}

# --- uv + Python 3.12 -------------------------------------------------------
if ! command -v uv >/dev/null; then
  log "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || warn "uv install failed"
  export_env PATH "$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null && { uv python install 3.12 >/dev/null 2>&1 || warn "python 3.12 install failed"; }

if [ -f backend/pyproject.toml ]; then
  log "uv sync (backend)"
  (cd backend && uv sync --all-extras --dev) || warn "uv sync failed"
fi

# --- Frontend ---------------------------------------------------------------
if [ -f frontend/package.json ]; then
  log "npm install (frontend)"
  if [ -f frontend/package-lock.json ]; then
    (cd frontend && npm ci --no-audit --no-fund) || warn "npm ci failed"
  else
    (cd frontend && npm install --no-audit --no-fund) || warn "npm install failed"
  fi
fi

# --- gh CLI (tickets live in GitHub Issues) ---------------------------------
if ! command -v gh >/dev/null; then
  log "installing gh"
  { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq gh; } >/dev/null 2>&1 || warn "gh install failed"
fi
# No GH_TOKEN needed: the session proxy authenticates `gh api` REST calls.
# `gh issue`/`gh pr` use GraphQL, which cloud sessions block; see docs/agents/issue-tracker.md.

# --- Postgres (stands in for Supabase local) --------------------------------
PG_USER=postgres PG_PASS=postgres
if ! command -v pg_ctlcluster >/dev/null && ! command -v pg_ctl >/dev/null; then
  log "installing postgresql"
  { $SUDO apt-get update -qq && $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql; } >/dev/null 2>&1 \
    || warn "postgresql install failed"
fi
if command -v service >/dev/null && ls /etc/init.d/postgresql >/dev/null 2>&1; then
  $SUDO service postgresql start >/dev/null 2>&1 || warn "postgres start failed"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    as_pg psql -qtAc 'select 1' >/dev/null 2>&1 && break
    sleep 1
  done
  as_pg psql -qc "alter user $PG_USER password '$PG_PASS';" >/dev/null 2>&1
  for db in voice_agent voice_agent_test voice_agent_e2e; do
    as_pg psql -qtAc "select 1 from pg_database where datname='$db'" | grep -q 1 \
      || as_pg createdb "$db" || warn "createdb $db failed"
  done
  export_env DATABASE_URL "postgresql+psycopg://$PG_USER:$PG_PASS@localhost:5432/voice_agent"
  export_env TEST_DATABASE_URL "postgresql+psycopg://$PG_USER:$PG_PASS@localhost:5432/voice_agent_test"
  # Playwright (frontend `npm run e2e`): tests/e2e/serve.sh migrates and seeds this one.
  export_env E2E_DATABASE_URL "postgresql+psycopg://$PG_USER:$PG_PASS@localhost:5432/voice_agent_e2e"
fi

# --- Session defaults -------------------------------------------------------
export_env TZ "America/New_York"
export_env APP_ENV "local"

log "done"
exit 0
