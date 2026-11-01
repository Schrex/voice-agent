# Progress

Work is tracked as GitHub issues #1–#37 on Schrex/voice-agent (thin vertical slices, native "blocked by" edges; issue number = ticket number).
Frontier = open issues with no open blockers: the **Frontier query** in `docs/agents/issue-tracker.md`.
docs/task-dependencies.md is the original layer-based plan, superseded by the issues for build order.

| Current | Status | Notes |
|---|---|---|
| #1 Backend skeleton with health check and CI | todo | Only unblocked ticket |

## Decisions log

- 2026-11-01: Product spec, architecture, task plan, ADRs 0001–0005 written.
- 2026-11-01: Spec broken into 37 thin-slice tickets (#1–#37) with per-ticket Definition of Done; #37 is ready-for-human.

## Open items

- Office line behavior for overnight transfers (rings where? voicemail?).
- Overnight Overdue SMS: send immediately (current default) or hold until morning.
- Safety-lead approval of the emergency line.
