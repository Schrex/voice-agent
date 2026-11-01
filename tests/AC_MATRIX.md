# Acceptance-criteria matrix

Every acceptance criterion in `docs/product-specification.md` §9, the test layer(s) that verify it, and where it stands. A change touching an AC updates its row and its test (AGENTS.md).

Layers (architecture §9): **U** domain unit · **I** API integration (real local Postgres) · **S** ElevenLabs simulation/agent test on the staging agent (`backend/agent/tests/*.json`, synced by `push.py`) · **P** Playwright · **L** live call script (#37).

Status: **done** = test exists and passes in CI · **defined** = test written in the repo but not yet run (S tests need the staging agent) · **deferred** = needs accounts (ElevenLabs, Twilio, staging) · **planned** = not built yet (ticket named).

| AC | Summary | Layer(s) | Ticket | Status | Tests |
|---|---|---|---|---|---|
| AC1.1 | First utterance: automated + recording disclosed | U, I, S, L | #5 | U/I done; S defined, deferred; L deferred | U `tests/unit/test_agent_config.py::test_first_message_is_automated_recorded_and_names_the_foreman`; I `tests/integration/test_agent_call_start_contract.py` (agent accepts call-start vars); S `backend/agent/tests/ac1_1_greeting_automated_and_recorded.json` |
| AC1.2 | Read back job, quantity, unit, time before submit | S, L | #7 | S defined, deferred; L deferred | S `backend/agent/tests/ac1_2_read_back_before_submit.json` (simulation), `backend/agent/tests/ac1_2_no_submit_before_confirmation.json` (tool, verify absence); correction `backend/agent/tests/j1_corrected_quantity_is_submitted.json` (tool); one question per turn `backend/agent/tests/j1_one_question_per_turn.json` (simulation) |
| AC1.3 | Alias → canonical job name read back | U, S | #13 | planned | |
| AC1.4 | No job match → Unmatched, no guess | U, I, S | #13 | planned | |
| AC1.5 | Needed-by asked once, then recorded unknown | U, S | #14 | planned | |
| AC1.6 | Two needs → two Recorded requests, both refs read | I, S | #15 | planned | |
| AC1.7 | Says recorded, not yet confirmed, gives ref | U, I, S, L | #6, #7 | U/I done; S defined, deferred; L deferred | U `tests/unit/test_agent_config.py::test_prompt_gives_the_spec_after_submit_sentence_verbatim`; I `tests/integration/test_submit_requests.py::test_valid_call_records_a_request_with_a_reference_and_an_agent_event`, `::test_references_are_sequential`, `tests/integration/test_agent_submit_tool_contract.py` (tool config reaches the endpoint, Recorded request with its ref); S `backend/agent/tests/ac1_7_recorded_not_yet_confirmed_with_reference.json` |
| AC1.8 | Hang-up before confirm → Draft, no Recorded | U, I, S, P | #28 | U/I/P done; S defined, deferred | I `tests/integration/test_drafts.py::test_hang_up_before_confirm_creates_a_draft_and_no_recorded_request`, `::test_draft_is_linked_to_its_call_and_has_an_audit_event`, `::test_a_call_that_submitted_a_request_creates_no_draft`, `::test_no_need_found_creates_no_draft`, `::test_repeat_delivery_creates_no_second_draft`; U `tests/unit/test_draft.py`, `tests/unit/test_call_outcome.py::test_call_with_a_draft`, `tests/unit/test_agent_config.py::test_data_collection_fields_are_the_ones_the_post_call_drafts_read`; S `backend/agent/tests/ac1_8_no_submit_when_foreman_leaves_before_confirming.json` (tool, verify absence); P (coordinator promotes the Draft) `tests/e2e/promote-draft.spec.ts`, I `tests/integration/test_drafts.py::test_coordinator_promotes_a_draft_to_recorded_with_an_audit_event` |
| AC1.9 | Today request → on-duty SMS within 60 s | I, L | #21 | planned | |
| AC2.1 | Same job + category → asks if it's the existing request | U, S | #18 | planned | |
| AC2.2 | "Yes" → no new request, note added | I, S | #18 | planned | |
| AC3.1 | Recorded → "office hasn't picked it up yet" | S | #16 | planned | |
| AC3.2 | Acknowledged → names Owner, not confirmed | S | #16 | planned | |
| AC3.3 | Resolved/Denied → denied + explanation | S | #16 | planned | |
| AC3.4 | No match → says so, offers Transfer/Callback | S | #16 | planned | |
| AC3.5 | "Need an answer today" → note + coordinator alerted, no new request | I, S | #17 | planned | |
| AC4.1 | Cancel Recorded → Resolved/Withdrawn, coordinator notified | I, S | #20 | planned | |
| AC4.2 | Change In Progress → unchanged, Change requested, "not yet changed" | I, S | #19 | planned | |
| AC5.1 | "Get me the office" → transfer next utterance, no reason asked | S, L | #25 | planned | |
| AC5.2 | Interrupted intake → Draft linked to call | I | #28 | done | `tests/integration/test_drafts.py::test_transfer_mid_intake_creates_a_draft_linked_to_the_call` |
| AC5.3 | Transfer → pop-up + SMS naming Foreman and Job before ring | I, P, L | #25 | planned | |
| AC5.4 | Callback Request → SMS on-duty + backup within 60 s, no time promised | I, S | #24 | planned | |
| AC6.1 | "We hit a gas line" → safety script first | S | #26 | planned | |
| AC6.2 | Emergency request + SMS all coordinators within 60 s | I, S, L | #26 | planned | |
| AC6.3 | Transfer to office line after safety line | S, L | #26 | planned | |
| AC6.4 | Never says help is coming / anyone reached | S | #26, #36 | planned | |
| AC7.1 | Quick-entry request in same queue and J3 lookup | I, S | #30 | planned | |
| AC8.1 | Unrostered: main office number, call ends, logged, nothing disclosed | I, P, S, L | #4, #5, #27, #34 | I/P done; S defined, deferred; L deferred | I `tests/integration/test_call_start.py::test_unrostered_*` (rejection line, attempt logged, no disclosure), `tests/integration/test_call_start.py::test_deactivated_foremans_number_is_rejected_at_call_start` and `tests/integration/test_admin_roster.py::test_deactivated_foreman_is_rejected_at_the_next_call_start` (a deactivated Foreman is treated as unrostered), `tests/integration/test_agent_call_start_contract.py::test_agent_allows_the_overrides_the_rejection_response_uses`, `tests/integration/test_post_call.py::test_rejected_call_keeps_outcome_rejected` (post-call record of the attempt keeps outcome `rejected`, with transcript and duration); P `tests/e2e/admin.spec.ts` "admin adds a foreman, then deactivates him…"; S `backend/agent/tests/ac8_1_rejected_caller_call_ends.json`, `backend/agent/tests/ac8_1_rejected_caller_nothing_disclosed.json` |
| AC9.1 | Acknowledge requires Owner | I, P | #11 | planned | |
| AC9.2 | Resolve requires Outcome + explanation | I, P | #12 | planned | |
| AC9.3 | Today not Acknowledged in 15 min → Overdue + backup SMS | U, I | #22 | planned | |
| AC9.4 | Resolved, not Foreman Informed in 2 h → Uninformed | U, I | #32 | planned | |
| AC9.5 | Every field change audited; no hard delete | I | #12 | planned | |
| J9 (no numbered AC) | Queue: open requests sorted urgency then age, refresh 10 s, times in America/New_York | I, P, U (Vitest) | #9 | done | I `tests/integration/test_queue.py`; P `tests/e2e/queue.spec.ts`; Vitest `frontend/src/QueuePage.test.tsx` |
| J9 detail (no numbered AC; supports AC9.5) | Request detail: all fields and audit history (who, when, before/after), oldest first, times in America/New_York | I, P, U (Vitest) | #10 | done | I `tests/integration/test_request_detail.py`; P `tests/e2e/request-detail.spec.ts`; Vitest `frontend/src/RequestDetailPage.test.tsx` |
| ACX.1 | Never states availability, ETA or unrecorded decision | S | #16, #36 | planned | |
| ACX.2 | Never asks about mood, day or productivity | S | #36 | planned | |

## Other verified behaviour (not a §9 AC)

Spec and architecture rules that are tested but have no AC id of their own.

| Rule | Source | Layer(s) | Ticket | Status | Tests |
|---|---|---|---|---|---|
| Backend/tool error mid-call → speakable error (HTTP 200), nothing half-written | Spec §8 "Backend/tool error mid-call" | I | #6 | done | `tests/integration/test_submit_requests.py::test_backend_error_returns_a_speakable_error_with_http_200`, `::test_failure_after_the_request_is_written_rolls_everything_back` |
| Foreman identity comes from the call; unrostered or unknown conversation or bad secret cannot write | ADR 0004, AC8.x | I | #6 | done | `tests/integration/test_submit_requests.py::test_foreman_id_in_the_tool_body_is_ignored`, `::test_unknown_conversation_is_rejected_and_nothing_written`, `::test_unrostered_callers_conversation_is_rejected_and_nothing_written`, `::test_missing_or_wrong_secret_is_rejected_and_nothing_written` |
| Lifecycle guard: only allowed transitions; others raise | Architecture §5 | U | #6 | done | `tests/unit/test_lifecycle.py` |
| Post-call webhook: HMAC verified (bad/missing → 401, nothing written), idempotent | Architecture §3.4, §10 | I | #27 | done | `tests/integration/test_post_call.py::test_bad_or_missing_signature_is_rejected_and_nothing_written`, `::test_same_payload_twice_is_one_update` |
