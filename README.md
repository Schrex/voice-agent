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

## Getting started

Setup and run commands land with task T01.
