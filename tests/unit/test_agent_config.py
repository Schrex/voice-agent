"""The agent config in backend/agent/ (ticket #5). Spoken behavior is checked by the EL tests
in backend/agent/tests/ (S layer); these check what is fixed in config before any LLM runs.
"""

import json
from typing import Any

from agent.push import AGENT_DIR, desired_agent, desired_tools, safety_line
from app.db.models import CATEGORIES
from app.domain.draft import DATA_COLLECTION_FIELDS

ENV = {
    "agent_name": "x",
    "backend_url": "https://b.example.test",
    "hook_secret_id": "s",
    "tool_secret_id": "t",
}
TOOL_IDS = {
    "find_jobs": "tool_find",
    "resolve_needed_by": "tool_resolve",
    "submit_requests": "tool_submit",
    "find_open_requests": "tool_status",
    "create_callback_request": "tool_callback",
    "add_note": "tool_note",
    "transfer_to_office": "tool_transfer",
    "find_duplicates": "tool_duplicates",
    "amend_request": "tool_amend",
    "start_emergency": "tool_emergency",
    "withdraw_request": "tool_withdraw",
}


def _agent() -> dict[str, Any]:
    agent: dict[str, Any] = desired_agent(ENV, TOOL_IDS)["conversation_config"]["agent"]
    return agent


def test_first_message_is_automated_recorded_and_names_the_foreman() -> None:
    """AC1.1: the first utterance is this fixed text for a rostered caller."""
    first = _agent()["first_message"]

    assert "automated" in first
    assert "recorded" in first
    assert "{{foreman_first_name}}" in first


def test_tools_are_the_system_tools_and_the_backend_tools() -> None:
    """end_call and transfer_to_number (#25) are built in; find_jobs (#13), resolve_needed_by
    (#14), submit_requests (#7), find_open_requests (#16), create_callback_request (#24),
    add_note (#17), transfer_to_office (#25), find_duplicates (#18), amend_request (#19),
    start_emergency (#26) and withdraw_request (#20) are attached by their workspace ids."""
    prompt = _agent()["prompt"]

    assert set(prompt["built_in_tools"]) == {"end_call", "transfer_to_number"}
    assert prompt["built_in_tools"]["end_call"]["params"] == {"system_tool_type": "end_call"}
    assert prompt["tool_ids"] == [
        "tool_find",
        "tool_resolve",
        "tool_submit",
        "tool_status",
        "tool_callback",
        "tool_note",
        "tool_transfer",
        "tool_duplicates",
        "tool_amend",
        "tool_emergency",
        "tool_withdraw",
    ]
    assert not prompt.get("tools")


def test_transfer_is_a_conference_to_the_office_line_from_settings() -> None:
    """Architecture §3.3: `transfer_to_number` (conference) to the Office Line. The number is
    the call-start `office_line_e164` variable (`settings`), so the Admin's number is the one
    dialled and there is no second copy in the agent config."""
    agent = _agent()
    params = agent["prompt"]["built_in_tools"]["transfer_to_number"]["params"]

    assert params["system_tool_type"] == "transfer_to_number"
    [transfer] = params["transfers"]
    assert transfer["transfer_type"] == "conference"
    assert transfer["transfer_destination"] == {
        "type": "phone_dynamic_variable",
        "phone_number": "office_line_e164",
    }
    assert transfer["condition"]
    placeholders = agent["dynamic_variables"]["dynamic_variable_placeholders"]
    assert placeholders["office_line_e164"] == ""


def test_prompt_transfers_on_request_after_telling_the_office() -> None:
    """Spec J5 / AC5.1: no reason asked; the office is told (`transfer_to_office`) first, then
    the spec sentence verbatim, then `transfer_to_number`. The S test checks the spoken
    behavior."""
    prompt = _agent()["prompt"]["prompt"]
    j5 = prompt[prompt.index("# J5") :]

    assert '"Connecting you to the office now."' in j5
    told, said, transferred = (
        j5.index("`transfer_to_office`"),
        j5.index('"Connecting you to the office now."'),
        j5.index("`transfer_to_number`"),
    )
    assert told < said < transferred
    assert "Never ask why" in j5


def test_prompt_offers_a_transfer_when_a_request_could_not_be_saved() -> None:
    """Spec §8 (tool error: offer Transfer) and AC3.4 (no match: offer Transfer): accepting the
    offer transfers the call as in J5 (open questions on #7 and #16)."""
    prompt = _agent()["prompt"]["prompt"]

    assert "could not be saved, and offer to put them through to the office" in prompt
    assert "If they accept the offer to be put through to the office, transfer them" in prompt


def test_prompt_gives_the_spec_after_submit_sentence_verbatim() -> None:
    """AC1.7 / spec J1 step 6: recorded, not yet confirmed. The S test checks it is spoken."""
    prompt = _agent()["prompt"]["prompt"]

    assert "Recorded and sent to the office. It isn't confirmed yet." in prompt
    assert "`submit_requests`" in prompt


def test_llm_is_claude_sonnet_5_5_in_english() -> None:
    agent = _agent()

    assert agent["prompt"]["llm"] == "claude-sonnet-5-5"
    assert agent["language"] == "en"


def test_data_collection_fields_are_the_ones_the_post_call_drafts_read() -> None:
    """#28: the post-call webhook builds a Draft from these fields (architecture §3.4)."""
    fields = desired_agent(ENV, TOOL_IDS)["platform_settings"]["data_collection"]

    assert tuple(fields) == DATA_COLLECTION_FIELDS
    assert all(field.get("description") for field in fields.values())
    assert fields["quantity"]["type"] == "number"
    assert fields["category"]["enum"] == list(CATEGORIES)


def test_prompt_has_the_job_matched_by_find_jobs_never_picked_by_the_agent() -> None:
    """Spec J1 step 3 / AC1.3, AC1.4: the backend matches; no match is Unmatched, not a guess.
    The S tests check the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "`find_jobs`" in prompt
    assert "job_spoken" in prompt
    assert "job_id" in prompt and "(job_id" not in prompt


def test_prompt_reads_back_the_needed_by_the_backend_resolved() -> None:
    """Ticket #14 / ADR 0004: the backend works out the day and time; the agent reads back what
    `resolve_needed_by` returned, and a needed-by the Foreman cannot give is left out (AC1.5).
    The S tests check the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "`resolve_needed_by`" in prompt
    assert "needed_by_resolved" in prompt
    assert "leave `needed_by_spoken` out" in prompt


def test_prompt_reports_status_in_the_spec_lifecycle_words() -> None:
    """Spec J3 step 3 / AC3.1-AC3.3: the status is looked up, never recalled, and reported in
    the lifecycle words verbatim; no match is said plainly with Transfer or Callback offered
    (AC3.4). The S tests check the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "`find_open_requests`" in prompt
    assert '"The office hasn\'t picked it up yet."' in prompt
    assert '"<owner> has it, not confirmed yet."' in prompt
    assert '"<owner> is working on it."' in prompt
    assert "read the `explanation` exactly as written" in prompt
    assert "can't find that request" in prompt
    assert "put them through to the office or to have someone call them back" in prompt


def test_prompt_splits_several_needs_into_one_numbered_summary_and_one_submit() -> None:
    """Ticket #15 / spec J1 step 4, AC1.6: several needs are separate items, read back as a
    numbered summary with one confirmation, submitted together, and every reference given.
    The S tests check the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "## Several needs" in prompt
    assert "numbered summary" in prompt
    assert "one `submit_requests` call" in prompt
    assert "every reference number" in prompt


def test_submit_tool_takes_every_confirmed_need_not_exactly_one() -> None:
    """Ticket #15: the tool schema tells the agent to send each confirmed need as its own item."""
    [tool] = [
        t["tool_config"]
        for t in desired_tools(ENV)
        if t["tool_config"]["name"] == "submit_requests"
    ]
    items = tool["api_schema"]["request_body_schema"]["properties"]["items"]

    assert "Exactly one" not in items["description"]
    assert "one item per need" in items["description"]
    assert "maxItems" not in items


def test_prompt_appends_a_note_or_urgency_to_the_existing_request() -> None:
    """Ticket #17 / spec J3 step 4, AC3.5: "need an answer today" is a note on the Request the
    lookup returned, sent with `add_note`, never a new Request; the agent says only that it was
    added. The S test checks the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "## Adding a note" in prompt
    assert "`add_note`" in prompt
    assert "do not call `submit_requests`" in prompt
    assert '"urgent": true' in prompt


def test_add_note_tool_takes_the_ref_the_text_and_an_optional_urgent_flag() -> None:
    """Architecture §4.2: `add_note(ref, text, urgent?)` → `{ok}`."""
    [tool] = [
        t["tool_config"] for t in desired_tools(ENV) if t["tool_config"]["name"] == "add_note"
    ]
    schema = tool["api_schema"]["request_body_schema"]

    assert set(schema["properties"]) == {"ref", "text", "urgent"}
    assert schema["properties"]["urgent"]["type"] == "boolean"
    assert schema["required"] == ["ref", "text"]


def test_prompt_amends_with_amend_request_and_says_the_spec_sentence_when_not_applied() -> None:
    """Ticket #19 / spec J4, AC4.2: the change goes through `amend_request` after a yes; when
    the backend did not apply it the agent says the J4 sentence verbatim. The S test checks the
    spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "# J4: Changing a Request" in prompt
    assert "`amend_request`" in prompt
    assert "I've flagged that for the office; it isn't changed yet." in prompt


def test_amend_tool_takes_the_ref_and_only_the_changeable_details() -> None:
    """Architecture §4.2: `amend_request(ref, changes)` → `{applied, status}`."""
    [tool] = [
        t["tool_config"] for t in desired_tools(ENV) if t["tool_config"]["name"] == "amend_request"
    ]
    schema = tool["api_schema"]["request_body_schema"]

    assert schema["required"] == ["ref", "changes"]
    assert set(schema["properties"]["changes"]["properties"]) == {
        "need",
        "quantity",
        "unit",
        "needed_by_spoken",
    }


def test_prompt_withdraws_with_withdraw_request_after_a_yes() -> None:
    """Ticket #20 / spec J4, AC4.1: the withdrawal goes through `withdraw_request` after a yes;
    when the backend did not apply it (In Progress or later) the agent says the J4 sentence
    verbatim. The S test checks the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]
    section = prompt[prompt.index("# J4: Withdrawing a Request") :]
    section = section[: section.index("\n# ", 1)]

    assert "`withdraw_request`" in section
    assert "only after they clearly say yes" in section
    assert "I've flagged that for the office; it isn't changed yet." in section


def test_withdraw_tool_takes_only_the_ref() -> None:
    """Architecture §4.2: `withdraw_request(ref)` → `{applied}`."""
    [tool] = [
        t["tool_config"]
        for t in desired_tools(ENV)
        if t["tool_config"]["name"] == "withdraw_request"
    ]
    schema = tool["api_schema"]["request_body_schema"]

    assert set(schema["properties"]) == {"ref"}
    assert schema["required"] == ["ref"]


def test_prompt_takes_a_callback_request_asking_one_optional_question() -> None:
    """Ticket #24 / spec J5 "Callback Request", AC5.4: one optional "What's it about?", a yes
    before recording, and never a callback time. The S tests check the spoken behavior."""
    prompt = _agent()["prompt"]["prompt"]

    assert "# J5: Callback Request" in prompt
    assert '"What\'s it about?"' in prompt
    assert "`create_callback_request`" in prompt
    assert "Never say when anyone will call back" in prompt


def test_accepting_the_callback_offer_after_a_failed_lookup_takes_a_callback_request() -> None:
    """AC3.4 (#16 left the Callback offer unwired): accepting it now leads to J5."""
    prompt = _agent()["prompt"]["prompt"]

    assert "If they accept the offer to have someone call them back" in prompt
    assert "put through or called back and you have no tool" not in prompt


def test_callback_tool_takes_only_the_optional_reason() -> None:
    """Architecture §4.2: `create_callback_request(reason?)`; the backend sets the rest."""
    [tool] = [
        t["tool_config"]
        for t in desired_tools(ENV)
        if t["tool_config"]["name"] == "create_callback_request"
    ]
    body = tool["api_schema"]["request_body_schema"]

    assert list(body["properties"]) == ["reason"]
    assert not body.get("required")


def test_prompt_checks_each_need_for_a_duplicate_before_the_read_back() -> None:
    """Ticket #18 / spec J2, AC2.1/AC2.2: the backend decides what is a duplicate
    (`find_duplicates`); the agent asks "Is this about your <need> request from <time>?";
    yes → `add_note` on that Request and no new Request, no → submitted as usual."""
    prompt = _agent()["prompt"]["prompt"]

    assert "# J2: Duplicate check" in prompt
    assert "`find_duplicates`" in prompt
    assert "Is this about your" in prompt
    assert "{{open_requests}}" in prompt
    section = prompt.split("# J2: Duplicate check", 1)[1].split("\n# ", 1)[0]
    assert "`add_note`" in section
    assert "`submit_requests`" in section


def test_find_duplicates_tool_takes_the_job_id_and_the_category() -> None:
    [tool] = [
        t["tool_config"]
        for t in desired_tools(ENV)
        if t["tool_config"]["name"] == "find_duplicates"
    ]
    schema = tool["api_schema"]["request_body_schema"]

    assert set(schema["properties"]) == {"job_id", "category"}
    assert schema["properties"]["job_id"]["type"] == "integer"
    assert schema["properties"]["category"]["enum"] == list(CATEGORIES)
    assert sorted(schema["required"]) == ["category", "job_id"]


# --- Emergency (ticket #26, spec J6) ---


def _j6() -> str:
    prompt: str = _agent()["prompt"]["prompt"]
    start = prompt.index("# J6: Emergency")
    end = prompt.find("\n# ", start + 1)
    return prompt[start : end if end != -1 else None]


def test_the_safety_line_is_the_approved_text_file_verbatim() -> None:
    """Ticket #26 DoD: the safety line spoken is exactly `backend/agent/safety_line.txt` (until
    the safety lead approves, the spec J6 placeholder, marked as placeholder in that file)."""
    line = safety_line()

    assert line == (
        "Stop work in the affected area and follow site procedures. Call 911 if anyone's hurt."
    )
    assert f'Say exactly: "{line}"' in _j6()


def test_safety_line_file_is_marked_as_a_placeholder_and_the_mark_is_never_spoken() -> None:
    raw = (AGENT_DIR / "safety_line.txt").read_text()

    assert "PLACEHOLDER" in raw  # remove the mark together with the approved wording
    assert "PLACEHOLDER" not in safety_line()
    assert "PLACEHOLDER" not in _agent()["prompt"]["prompt"]


def test_prompt_j6_safety_line_first_then_record_then_transfer() -> None:
    """Spec J6 steps 2-4 / AC6.1-AC6.3: the safety line before any other question, then
    `start_emergency`, then the J5 sentence, then `transfer_to_number`."""
    j6 = _j6()

    said, recorded, connecting, transferred = (
        j6.index(safety_line()),
        j6.index("`start_emergency`"),
        j6.index('"Connecting you to the office now."'),
        j6.index("`transfer_to_number`"),
    )
    assert said < recorded < connecting < transferred
    assert "before anything else" in j6


def test_prompt_j6_overrides_a_plain_transfer_at_any_point() -> None:
    """Spec J6 step 1: safety keywords at any point override a plain Transfer request."""
    prompt = _agent()["prompt"]["prompt"]
    rules = prompt[prompt.index("# Rules for every call") : prompt.index("# J8")]
    j6 = _j6()

    for keyword in ("injury", "utility strike", "gas", "collapse", "fire"):
        assert keyword in j6
    assert "never use `transfer_to_office`" in j6
    assert "J6: Emergency" in rules


def test_prompt_j6_never_says_help_is_coming_or_anyone_was_reached() -> None:
    """Spec J6 step 5 / AC6.4."""
    j6 = _j6()

    assert "Never say that help is on the way or coming" in j6
    assert "that anyone has been reached" in j6


def test_transfer_to_number_condition_covers_an_emergency() -> None:
    """Architecture §3.3: the Emergency transfers to the same Office Line (spec §4)."""
    params = _agent()["prompt"]["built_in_tools"]["transfer_to_number"]["params"]
    [transfer] = params["transfers"]

    assert "Emergency" in transfer["condition"]


def test_start_emergency_tool_takes_the_summary_and_the_job_if_said() -> None:
    """Architecture §4.2: `start_emergency(summary, job_id?, job_spoken?)` → `{ref}`."""
    [tool] = [
        t["tool_config"]
        for t in desired_tools(ENV)
        if t["tool_config"]["name"] == "start_emergency"
    ]
    body = tool["api_schema"]["request_body_schema"]

    assert list(body["properties"]) == ["summary", "job_id", "job_spoken"]
    assert body["properties"]["job_id"]["type"] == "integer"
    assert body["required"] == ["summary"]


def test_every_emergency_simulation_checks_the_exact_safety_line() -> None:
    """The S tests judge the spoken line against the approved file's text, word for word."""
    tests = [
        json.loads(path.read_text())
        for path in sorted((AGENT_DIR / "tests").glob("*.json"))
        if path.name.startswith(("ac6_", "j6_"))
    ]

    assert len(tests) == 5
    for test in tests:
        if test["name"].startswith("J6 transfers"):
            continue
        assert any(f'"{safety_line()}"' in c for c in test["success_conditions"]), test["name"]
