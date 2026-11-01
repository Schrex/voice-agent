"""The agent config in backend/agent/ (ticket #5). Spoken behavior is checked by the EL tests
in backend/agent/tests/ (S layer); these check what is fixed in config before any LLM runs.
"""

from typing import Any

from agent.push import desired_agent

ENV = {"agent_name": "x", "backend_url": "https://b.example.test", "hook_secret_id": "s"}


def _agent() -> dict[str, Any]:
    agent: dict[str, Any] = desired_agent(ENV)["conversation_config"]["agent"]
    return agent


def test_first_message_is_automated_recorded_and_names_the_foreman() -> None:
    """AC1.1: the first utterance is this fixed text for a rostered caller."""
    first = _agent()["first_message"]

    assert "automated" in first
    assert "recorded" in first
    assert "{{foreman_first_name}}" in first


def test_end_call_is_the_only_tool() -> None:
    """#5 scope: no server tools yet; end_call lets the agent hang up on a rejected caller."""
    prompt = _agent()["prompt"]

    assert set(prompt["built_in_tools"]) == {"end_call"}
    assert prompt["built_in_tools"]["end_call"]["params"] == {"system_tool_type": "end_call"}
    assert not prompt.get("tool_ids") and not prompt.get("tools")


def test_llm_is_claude_sonnet_5_5_in_english() -> None:
    agent = _agent()

    assert agent["prompt"]["llm"] == "claude-sonnet-5-5"
    assert agent["language"] == "en"
