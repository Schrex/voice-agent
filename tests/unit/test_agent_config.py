"""The agent config in backend/agent/ (ticket #5). Spoken behavior is checked by the EL tests
in backend/agent/tests/ (S layer); these check what is fixed in config before any LLM runs.
"""

from typing import Any

from agent.push import desired_agent, desired_tools
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
    "add_note": "tool_note",
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


def test_tools_are_end_call_and_the_backend_tools() -> None:
    """end_call (built-in) hangs up; find_jobs (#13), resolve_needed_by (#14),
    submit_requests (#7), find_open_requests (#16) and add_note (#17) are attached by their
    workspace ids."""
    prompt = _agent()["prompt"]

    assert set(prompt["built_in_tools"]) == {"end_call"}
    assert prompt["built_in_tools"]["end_call"]["params"] == {"system_tool_type": "end_call"}
    assert prompt["tool_ids"] == [
        "tool_find",
        "tool_resolve",
        "tool_submit",
        "tool_status",
        "tool_note",
    ]
    assert not prompt.get("tools")


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
