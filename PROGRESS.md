# Progress

Status of tasks in [docs/task-dependencies.md](docs/task-dependencies.md). Statuses: `todo` · `in progress` · `done` · `blocked`.

| ID | Task | Status | Notes |
|---|---|---|---|
| T01 | Repo + tooling + CI skeleton | todo | |
| T02 | Supabase projects + Alembic schema | todo | |
| T03 | Domain: lifecycle, SLA, dedupe | todo | |
| T04 | Domain: job matching + time parsing | todo | |
| T05 | Services: requests + audit | todo | |
| T06 | Seed/admin data | todo | |
| T07 | Webhook: call-start | todo | |
| T08 | Agent tool endpoints | todo | |
| T09 | Webhook: post-call + Drafts | todo | |
| T10 | Alerts: SMS, email, pop-ups | todo | |
| T11 | Scheduler jobs | todo | |
| T12 | Agent as code | todo | |
| T13 | EL simulation tests per AC | todo | |
| T14 | Dashboard API + JWT | todo | |
| T15 | Dashboard UI: queue, detail, actions | todo | |
| T16 | Dashboard UI: quick entry, pop-ups, admin | todo | |
| T17 | Staging deploy | todo | |
| T18 | Live call scripts + AC sign-off | todo | |
| T19 | Prod deploy + launch gates | todo | |

## Decisions log

- 2026-11-01: Product spec, architecture, task plan, ADRs 0001–0005 written.

## Open items

- Office line behavior for overnight transfers (rings where? voicemail?).
- Overnight Overdue SMS: send immediately (current default) or hold until morning.
- Safety-lead approval of the emergency line.
