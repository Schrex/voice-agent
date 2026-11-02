# Product Specification — Field Request Assistant (Pilot v1)

Status: Draft for review · Owner: Sumanth · Date: 2026-11-01
Vocabulary: see [GLOSSARY.md](../GLOSSARY.md). Decisions: see [docs/adr](adr/).

---

## 1. Purpose

Foremen phone the office with operational needs (trucks, equipment, material, labor). Calls get missed, requests get lost, and foremen call repeatedly to find out whether anyone is handling them.

**Core promise to foremen:** *"You don't have to keep calling to find out whether somebody is handling your request."*

The product captures every request reliably, gives each one a human owner, tracks it to a stated outcome, and lets the foreman check status with one short call. It does not replace the office or make decisions on its behalf.

The central object is the **Request**, not the call or transcript. A transcript is evidence; a request is something someone acts on.

## 2. Scope

### In scope (v1 pilot)

- AI voice intake on a dedicated pilot number (later: missed-call forwarding from the main line)
- Request capture with read-back confirmation, multi-need splitting, duplicate detection
- Status lookup by phone
- Amend / withdraw by phone
- Live **Transfer** to the office line on request, with a dashboard pop-up + SMS so the office knows who is calling
- **Callback Request** on foreman's request
- **Emergency** handling: safety line, transfer to the office line, alert all coordinators
- Office dashboard: shared queue for AI-captured and human-logged requests
- Coordinator alerts (SMS / email)
- Audit trail on every request change

### Out of scope (v1)

| Not built | Why |
|---|---|
| Proactive SMS/push status updates to foremen | Parked; foreman learns outcome from a person or status lookup ([ADR 0002](adr/0002-no-proactive-foreman-notifications.md)) |
| Unrostered callers | Rostered foremen only ([ADR 0001](adr/0001-rostered-callers-only.md)) |
| Autonomous scheduling, dispatch, or approvals | Humans decide; AI records |
| AI statements of availability, schedules, or ETAs | AI only reports what a person recorded |
| AI-generated production targets or tomorrow briefings | Planning data not yet verified |
| ERP / HCSS integration | Job list maintained manually for pilot |
| Sentiment, emotion, or performance scoring | Trust; no surveillance |
| Mandatory daily check-ins | Foremen never required to report to get help |
| Languages other than English | Pilot crews are English-speaking |
| Owner logins | Owners assigned by name; coordinator updates on their behalf |
| Multi-company tenancy | Schreiber Excavating only |

### Later phases (non-binding; unlocked by pilot results)

Missed-call coverage on main line → proactive foreman notifications → verified tomorrow briefings → optional end-of-day updates → HCSS job/equipment sync → multi-tenant.

## 3. Actors

| Actor | Uses | Responsibilities |
|---|---|---|
| **Foreman** | Phone only | Calls in needs, checks status, amends/withdraws, asks for a person |
| **Coordinator** | Dashboard + phone + SMS alerts | Answers calls, logs human-answered requests, acknowledges and sets owner, moves to resolution, informs foreman |
| **Owner** | Nothing (v1) | Fulfills the request; status updated by a coordinator |
| **Admin** | Dashboard | Maintains roster, jobs (with aliases), owners, office line number, duty roster |

Pilot: one Staff role. Every staff member can do both Coordinator and Admin work, and "all coordinators" means everyone on the staff list ([ADR 0006](adr/0006-one-staff-role-for-the-pilot.md)).

## 4. Operating parameters

| Parameter | v1 value | Notes |
|---|---|---|
| Coverage | **24/7, single mode** | No business-hours distinction in v1; all behavior below applies at all times |
| Access | Rostered numbers only | Multiple numbers per foreman allowed |
| Transfer target | Dedicated office line | Used for both Transfer and Emergency; the AI cannot detect whether anyone answered ([ADR 0003](adr/0003-elevenlabs-native-telephony.md)) |
| Ack window — Today / Callback | 15 min | Placeholder; recalibrate from baseline (days 1–5) |
| Ack window — Planned | 2 h | Placeholder |
| Ack window — Emergency, and no Urgency (needed-by unknown, Drafts) | Same as Today (15 min) | Product owner, 2026-11-02: every Recorded request can go Overdue |
| Uninformed threshold | 2 h after Resolved | Placeholder |
| Recording retention | 90 days (audio + transcript) | Request records kept indefinitely |
| Recording access | Coordinators, Admin | |

Consequence of 24/7 single mode: a Transfer or Callback at 2 AM behaves exactly as at 2 PM — a Transfer rings the office line, and an unacknowledged Callback Request goes Overdue after 15 min and alerts the backup coordinator. **No overnight coverage is staffed**: overnight requests are accepted as Overdue until the office picks them up in the morning. Because the AI never promises a callback time, it tells the foreman: *"I've sent it to the office. I can't tell you when someone will call back."* Emergencies still transfer to the office line and SMS all coordinators at any hour. Revisit if overnight alerts cause fatigue.

## 5. Request model

**Fields:** reference number (e.g. R-104), foreman, job (or *Unmatched*), category, what's needed, quantity + unit (if countable), needed-by, urgency, status, owner, outcome + explanation, foreman informed (y/n), notes, source (AI call / coordinator-logged), linked call recording + transcript, audit log.

**Categories:** Trucking, Equipment, Equipment Repair, Material, Labor, Information, Callback, Other. Category sets the default owner.

**Urgency:** Emergency (danger → safety line + alert + transfer, never queue-only) · Today (needed today or work stopped) · Planned (tomorrow or later). AI infers from needed-by and keywords and states it back.

**Lifecycle**

| Status | Meaning | Set by |
|---|---|---|
| Draft | Not confirmed by foreman (hang-up, drop, unresolved detail, interrupted by Transfer) | AI |
| Recorded | Foreman confirmed; no human has seen it | AI or coordinator |
| Acknowledged | Coordinator accepted responsibility **and** set an owner | Coordinator |
| In Progress | Owner acting; outcome unknown | Coordinator |
| Resolved | Finished, with Outcome (Fulfilled / Partially Fulfilled / Denied / Withdrawn) + explanation | Coordinator, or AI for foreman withdrawal before In Progress |

**Flags (dashboard):** Overdue (not Acknowledged within ack window) · Uninformed (Resolved, not Foreman Informed within threshold; never a request merged into another, and a phone withdrawal counts as Foreman Informed) · Unmatched job · Change requested · Has unknown fields.

## 6. User journeys and desired behavior

### J1 — Foreman submits a request (primary)

1. Rostered foreman calls. AI: identifies itself as automated, states the call is recorded, asks what they need. No small talk.
2. AI extracts job, category, need, quantity + unit, needed-by. For each missing field, asks **one question at a time, once**.
3. Job is matched against the active job list incl. aliases and **read back** ("Route 104 job"). No confident match → job recorded as *Unmatched*; never guessed.
4. Multiple needs → separate requests; AI reads a **numbered summary** and asks for one confirmation.
5. Critical values (job, quantity, unit, time) are read back before submit. Foreman can correct any item.
6. On "yes": request(s) → Recorded. AI gives reference number(s) and says explicitly: *"Recorded and sent to the office. It isn't confirmed yet."*
7. Still-missing fields after one ask → submitted marked *unknown*, not blocked.
8. Today-urgency → SMS alert to on-duty coordinator. Planned → dashboard + end-of-day summary email.

### J2 — Duplicate check (inside J1)

If the foreman has an open request on the same job + category, AI asks: *"Is this about your <need> request from <time>?"*
- Yes → note added / flagged on existing request; owner and coordinator notified; no new request.
- No → new request created.
Coordinators can also merge duplicates on the dashboard.

### J3 — Foreman checks status

1. Foreman: "Any word on that truck?"
2. AI finds matching open request(s); if ambiguous, asks which one (listing by need + job).
3. AI reports **exactly** the recorded state, using lifecycle words: Recorded → "the office hasn't picked it up yet"; Acknowledged → "<owner> has it, not confirmed yet"; In Progress → "<owner> is working on it"; Resolved → outcome + explanation as written.
4. Foreman may add urgency or a note ("need an answer today") → appended to the existing request and coordinator alerted.
5. Status unavailable / no match → AI says so plainly and offers a Transfer or Callback Request. Never guesses.

### J4 — Foreman amends or withdraws

- Before In Progress: AI applies the change (or resolves as Withdrawn and marks it Foreman Informed, since the foreman withdrew it himself), reads it back, notifies coordinator/owner.
- At/after In Progress: AI adds a note, flags *Change requested*, and tells the foreman *"I've flagged that for the office; it isn't changed yet."*

### J5 — Foreman wants to talk to the office (Transfer)

1. At **any point**, phrases like "let me talk to someone", "get me the office", "put me through" → AI says *"Connecting you to the office now."* and transfers to the office line. No argument, no reason required, intake not finished first.
2. Just before transferring, the office is told who is coming: a dashboard pop-up and an SMS to the on-duty coordinator — *"Incoming transfer: <foreman>, <job>, about: <need or 'not stated'>"*.
3. Any half-captured request is saved as Draft (via post-call processing) and linked to the call.
4. The AI drops out once transferred. It cannot detect an unanswered transfer; that risk is accepted for v1 ([ADR 0003](adr/0003-elevenlabs-native-telephony.md)).

**Callback Request** (any time the foreman asks "have someone call me back"): AI asks one optional question, *"What's it about?"*, then records a Callback Request (urgency Today, 15-min ack window) → SMS to on-duty and backup coordinators. AI never promises a callback time.

### J6 — Emergency

1. Trigger: safety keywords (injury, utility strike, gas, collapse, fire, etc.) at any point — overrides a plain Transfer request.
2. AI says the **safety-lead-approved** line (placeholder: *"Stop work in the affected area and follow site procedures. Call 911 if anyone's hurt."*), then *"Connecting you to the office now."*
3. Backend records an Emergency request and immediately SMS-alerts **all** coordinators: *"EMERGENCY call from <foreman>, <job>: <summary>"*, plus a dashboard pop-up.
4. AI transfers to the office line.
5. AI never says "help is on the way" or that anyone has been reached.

### J7 — Coordinator answers the call (human path)

Normal conversation; AI not involved. For actionable needs from pilot foremen, the coordinator logs a request via a quick-entry form (target < 30 s). It enters the same queue at Recorded or directly at Acknowledged. Status lookup (J3) then covers it.

### J8 — Unrostered caller

AI: *"This line is for registered crew leaders. Please call the office at <main number>."* Hangs up. Attempt logged. No intake, no Transfer, no information disclosed.

### J9 — Coordinator works the queue

Dashboard shows open requests sorted by urgency then age, with Overdue / Uninformed / Unmatched / Change-requested flags and counts (Open, Needs action, Overdue).

Actions: Acknowledge (owner required) · Edit fields / fix job · Add note · Merge duplicates · Reassign owner · Move to In Progress · Resolve (outcome + explanation required) · Mark Foreman Informed · Create request · Play recording / read transcript.

Every change audit-logged (who, when, before/after). No hard delete.

Alerts: SMS for new Today, Callback, Emergency (FYI), and Overdue (to backup coordinator). Planned → dashboard + end-of-day email.

## 7. Agent behavior rules

| Rule | Behavior |
|---|---|
| Transparent | Always identifies itself as automated; discloses recording |
| Brief | No small talk; one clarification at a time |
| Respectful of competence | No explaining field basics unless asked |
| Accurate | Uses lifecycle words exactly; Recorded ≠ Acknowledged ≠ confirmed |
| Speaks only to the record | Never states availability, schedules, ETAs, or decisions not written by a person; Information requests are recorded, not answered |
| Preserves autonomy | Caller can stop, correct, or reach a person at any time |
| No surveillance | No sentiment, emotion, or performance scoring; never asks how the day went |
| Follows through | Every confirmed request lands in the queue with an ack window |

## 8. Failure handling

| Failure | Required behavior |
|---|---|
| Job misheard | Read-back + correction; no confident match → Unmatched |
| Quantity / unit / time misheard | Read-back before submit |
| Several needs in one breath | Split + numbered summary |
| Duplicate | J2 check |
| Office never acknowledges | Overdue flag + SMS to backup coordinator |
| Status not found | Say so; offer Transfer / Callback |
| Hang-up or dropped call mid-intake | Save Draft; never submit as Recorded |
| Poor connection | Ask to repeat once; then offer Transfer / Callback |
| Transfer unanswered | Not detectable in v1 (accepted). Office was pre-notified by pop-up + SMS, so it can call back |
| Emergency transfer unanswered | Not detectable; mitigated by safety line given before transfer and SMS to all coordinators |
| Backend/tool error mid-call | Tell foreman the request could not be saved; offer Transfer; log incident |
| Office not using queue | Operational failure: named on-duty coordinator + backup every day; Overdue/Uninformed counts reviewed weekly |

## 9. Acceptance criteria

Verified by scripted test calls and dashboard checks before any foreman uses the system (days 6–12), and re-run after any agent change.

**J1 — Intake**
- AC1.1 Given a rostered number, when the call connects, then the AI identifies itself as automated and discloses recording within its first utterance.
- AC1.2 Given a foreman states job, need, quantity, and time, when the AI summarizes, then it reads back job, quantity, unit, and time before asking to submit.
- AC1.3 Given a spoken job alias in the job list, when matched, then the canonical job name is read back.
- AC1.4 Given a job name matching no job, when submitted, then the request has job *Unmatched* and no job is guessed.
- AC1.5 Given a missing needed-by, when the AI asks once and the foreman can't answer, then the request is Recorded with needed-by *unknown*.
- AC1.6 Given two needs in one utterance, when confirmed, then two Recorded requests exist with distinct reference numbers, both read out.
- AC1.7 Given a confirmed submit, then the AI says the request is recorded and **not yet confirmed**, and gives the reference number.
- AC1.8 Given the foreman hangs up before confirming, then a Draft exists and no Recorded request is created.
- AC1.9 Given a Today request is Recorded, then the on-duty coordinator receives an SMS within 60 s.

**J2 — Duplicates**
- AC2.1 Given an open Trucking request on Route 104 by the same foreman, when they request a truck for Route 104, then the AI asks whether it's about the existing request.
- AC2.2 Given the foreman answers yes, then no new request is created and a note is added to the existing one.

**J3 — Status**
- AC3.1 Given a Recorded request, when asked, then the AI says the office hasn't picked it up yet — never that it is confirmed.
- AC3.2 Given an Acknowledged request with owner Dispatch, then the AI names Dispatch and says it isn't confirmed.
- AC3.3 Given a Resolved/Denied request, then the AI states it was denied and reads the explanation.
- AC3.4 Given no matching request, then the AI says it can't find one and offers Transfer or Callback.
- AC3.5 Given the foreman adds "need an answer today", then a note is appended to the existing request and the coordinator is alerted; no new request is created.

**J4 — Amend / withdraw**
- AC4.1 Given a Recorded request, when the foreman cancels it, then it becomes Resolved/Withdrawn and the coordinator is notified.
- AC4.2 Given an In Progress request, when the foreman changes the time, then the request is unchanged, flagged *Change requested*, and the AI says it is not yet changed.

**J5 — Transfer**
- AC5.1 Given mid-intake, when the foreman says "get me the office", then the AI begins transfer within its next utterance without asking for a reason.
- AC5.2 Given the transfer is interrupted intake, then a Draft linked to the call exists.
- AC5.3 Given a transfer starts, then the dashboard shows an incoming-transfer pop-up and the on-duty coordinator receives an SMS naming the foreman and job before the office line rings.
- AC5.4 Given the foreman asks for a callback and confirms, then a Callback Request exists, on-duty and backup coordinators receive SMS within 60 s, and the AI does not promise a callback time.

**J6 — Emergency**
- AC6.1 Given "we hit a gas line", when said at any point, then the AI delivers the approved safety script before any other question.
- AC6.2 Given an emergency, then an Emergency request exists and all coordinators receive an SMS within 60 s, before or as the transfer starts.
- AC6.3 Given an emergency, then the call is transferred to the office line after the safety line.
- AC6.4 In no test does the AI say help is coming or that anyone has been reached.

**J7 — Human-logged**
- AC7.1 Given a coordinator logs a request via quick entry, then it appears in the same queue and is returned by J3 status lookup.

**J8 — Unrostered**
- AC8.1 Given an unrostered number, then the AI gives the main office number, ends the call, logs the attempt, and discloses no job or request information.

**J9 — Dashboard**
- AC9.1 Acknowledge cannot be saved without an owner.
- AC9.2 Resolve cannot be saved without an outcome and explanation.
- AC9.3 A Today request not Acknowledged within 15 min shows Overdue and the backup coordinator gets an SMS.
- AC9.4 A Resolved request not marked Foreman Informed within 2 h shows Uninformed.
- AC9.5 Every field change appears in the audit log with user and timestamp; no request can be hard-deleted.

**Cross-cutting**
- ACX.1 Across the test suite, the AI never states availability, ETA, or a decision not present in the request record.
- ACX.2 The AI never asks about mood, how the day went, or productivity.

## 10. Pilot success scorecard (day 30)

Initial thresholds — adjust after the days 1–5 baseline. With 2–3 foremen, review every failure individually, not just percentages.

| Measure | Target |
|---|---|
| Critical-field accuracy (job, resource, quantity, needed-by) | ≥ 95% |
| Acknowledged within ack window | ≥ 90% |
| Correct status reporting (no false confirmations) | 100% |
| Foremen who say it saves effort | ≥ 80% |

Also tracked: repeat calls per request, unresolved requests, Uninformed count, Transfer rate, Callback rate, Draft rate, time to acknowledgment vs baseline.

Day-30 decision: expand coverage / fix office workflow first / stop — per pilot plan §11.

## 11. Launch gates (before first foreman)

- [ ] Safety lead approves the emergency safety line
- [ ] Company reviews recording consent, retention, and access policy
- [ ] Roster, job list (with aliases), owners per category, office line number entered
- [ ] Named on-duty coordinator + backup for every working day of the pilot (overnight requests go Overdue until morning — accepted)
- [ ] Office line behavior for overnight transfers known (rings where? voicemail?)
- [ ] All §9 acceptance criteria pass on scripted calls, incl. noisy/poor-connection variants
- [ ] Transfer and emergency transfer tested to the real office line

## 12. Open items

- Overnight Overdue SMS alerts: send immediately. Decided by the product owner 2026-11-02 (the v1 default); coordinators may silence phones.
- Ack-window and Uninformed thresholds are placeholders pending baseline.
- Exact Today-vs-Planned inference rules (e.g. cut-off hour for "tomorrow morning" requests made late at night).
