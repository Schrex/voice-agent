"""The agent config in backend/agent/ (ticket #5). Spoken behavior is checked by the EL tests
in backend/agent/tests/ (S layer); these check what is fixed in config before any LLM runs.
"""

from typing import Any

from agent.push import desired_agent
from app.db.models import CATEGORIES
from app.domain.draft import DATA_COLLECTION_FIELDS

ENV = {
    "agent_name": "x",
    "backend_url": "https://b.example.test",
    "hook_secret_id": "s",
    "tool_secret_id": "t",
}
TOOL_IDS = {"submit_requests": "tool_submit"}


def _agent() -> dict[str, Any]:
    agent: dict[str, Any] = desired_agent(ENV, TOOL_IDS)["conversation_config"]["agent"]
    return agent


def test_first_message_is_automated_recorded_and_names_the_foreman() -> None:
    """AC1.1: the first utterance is this fixed text for a rostered caller."""
    first = _agent()["first_message"]

    assert "automated" in first
    assert "recorded" in first
    assert "{{foreman_first_name}}" in first


def test_tools_are_end_call_and_submit_requests() -> None:
    """end_call (built-in) hangs up; submit_requests (#7) is attached by its workspace id."""
    prompt = _agent()["prompt"]

    assert set(prompt["built_in_tools"]) == {"end_call"}
    assert prompt["built_in_tools"]["end_call"]["params"] == {"system_tool_type": "end_call"}
    assert prompt["tool_ids"] == ["tool_submit"]
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
