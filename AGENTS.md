# AGENTS.md

Voice agent that captures foremen's phoned-in requests and tracks each to a resolution. Pilot for Schreiber Excavating.

## Read before working

- `GLOSSARY.md`: canonical domain words. Use them verbatim in code, prompts, UI copy and commits (Job, not Project; Acknowledged, not Assigned).
- `docs/product-specification.md`: behavior and acceptance criteria (AC*). The spec wins over code; flag any conflict.
- `docs/architecture.md`: stack, interfaces, data model, layering.
- `docs/task-dependencies.md`: tasks T01–T19 and their order.
- `docs/adr/`: decisions already made. Reopen one only by writing a superseding ADR.

## Working rules

- Pick the next task whose dependencies are done in `PROGRESS.md`; update `PROGRESS.md` when a task starts and when its "done when" criterion is met.
- Backend owns every rule (ADR 0004). The voice agent gathers and confirms; lifecycle guards, time parsing, dedupe and caller identity live in `backend/app/domain` and `services`.
- Layering: `http` → `services` → `domain` + `db` + `integrations`. `domain` is pure: no I/O, no imports from other layers.
- Every request write goes through `services/` and writes a `request_events` row in the same transaction. Requests are never hard-deleted.
- The voice agent speaks only facts present in the request record: lifecycle words exactly as defined, never availability, ETAs or decisions.
- Agent prompt, tool schemas and EL tests live in `backend/agent/` and reach ElevenLabs only via `push.py`; edits made in the EL web UI get overwritten.
- Every AC maps to a test layer in `tests/AC_MATRIX.md`; a change touching an AC updates its test.
- Times: store UTC, parse and display America/New_York.

## Agent skills

### Issue tracker

GitHub Issues on Schrex/voice-agent, via `gh api` (REST; `gh issue`/`gh pr` fail in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Cloud sessions

Tickets can run in parallel on claude.ai/code. Setup and rules: `docs/agents/cloud-sessions.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
