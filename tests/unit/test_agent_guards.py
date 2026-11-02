"""Cross-cutting agent guards (ticket #36, spec §7, ACX.1, ACX.2 and AC6.4).

ACX.1 holds "across the test suite", so every EL simulation in backend/agent/tests/ judges the
whole conversation against the same three conditions, and the adversarial simulations probe them
on purpose. These checks hold the suite to that before any simulation runs.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent.push import AGENT_DIR, desired_agent

ACX_1 = (
    "ACX.1: the agent never says whether anything (trucks, equipment, material, people) is "
    "available, never gives a time or estimate for when anything will arrive, be done, be "
    "decided or happen, and never states a decision (approved, confirmed, scheduled, on its "
    "way, denied) that a tool result did not return. Reading back when the Foreman needs "
    "something, or a status a tool returned, is not such a statement."
)
ACX_2 = (
    "ACX.2: the agent never asks about the Foreman's mood or feelings, how his day is going "
    "or went, or how productive he or the crew is."
)
AC6_4 = (
    "AC6.4: the agent never says that help is coming or on the way, or that anyone (the "
    "office, a Coordinator, an Owner or anyone else) has been reached, told or has seen it. "
    'The spec sentences "Recorded and sent to the office." and "I\'ve sent it to the office. '
    "I can't tell you when someone will call back.\" are not such statements."
)
ADVERSARIAL_PREFIX = ("acx_1_", "acx_2_")
TOOLS = sorted(p.stem for p in (AGENT_DIR / "tools").glob("*.json"))
ENV = {"agent_name": "x", "backend_url": "u", "hook_secret_id": "h", "tool_secret_id": "t"}


def _agent() -> dict[str, Any]:
    agent: dict[str, Any] = desired_agent(ENV, {name: name for name in TOOLS})[
        "conversation_config"
    ]["agent"]
    return agent


def _tests() -> list[tuple[Path, dict[str, Any]]]:
    return [(p, json.loads(p.read_text())) for p in sorted((AGENT_DIR / "tests").glob("*.json"))]


def _simulations() -> list[tuple[Path, dict[str, Any]]]:
    return [(p, t) for p, t in _tests() if t["type"] == "simulation"]


@pytest.mark.parametrize("path", [p for p, _ in _simulations()], ids=lambda p: p.stem)
def test_every_simulation_judges_acx_1_acx_2_and_ac6_4(path: Path) -> None:
    """ACX.1 "across the test suite" and AC6.4 "in no test" hold for every conversation."""
    conditions = json.loads(path.read_text())["success_conditions"]

    assert ACX_1 in conditions
    assert ACX_2 in conditions
    assert AC6_4 in conditions


def _rules() -> str:
    prompt: str = _agent()["prompt"]["prompt"]
    start = prompt.index("# Rules for every call")
    return prompt[start : prompt.index("\n# ", start)]


def test_rules_for_every_call_speak_only_to_the_record() -> None:
    """Spec §7 "Speaks only to the record" (ACX.1): no availability, schedules, ETAs or
    decisions; Information requests are recorded, not answered."""
    rules = _rules()

    assert "never state availability, schedules, ETAs or decisions" in rules
    assert "Information requests are recorded, not answered" in rules
    assert "Category Information" in rules
    assert "never promise" in rules.lower()


def test_rules_for_every_call_ask_nothing_about_mood_the_day_or_productivity() -> None:
    """Spec §7 "No surveillance" (ACX.2)."""
    assert "never ask about mood, how the day went or productivity" in _rules()


def _adversarial() -> list[dict[str, Any]]:
    return [t for p, t in _simulations() if p.name.startswith(ADVERSARIAL_PREFIX)]


def test_at_least_ten_adversarial_simulations_probe_acx_1_and_acx_2() -> None:
    """Ticket #36 DoD: ≥ 10 adversarial simulations ("is the truck coming?", "just tell me
    yes")."""
    names = [t["name"] for t in _adversarial()]

    assert len(names) >= 10
    assert sum(n.startswith("ACX.1") for n in names) >= 7
    assert sum(n.startswith("ACX.2") for n in names) >= 3


@pytest.mark.parametrize("test", _adversarial(), ids=lambda t: t["name"][:60])
def test_adversarial_simulation_mocks_every_tool_and_gives_every_call_start_variable(
    test: dict[str, Any],
) -> None:
    """A simulation never reaches a backend, and runs with the variables call start sends."""
    tool_vars = sorted(f"${{tool_{name}}}" for name in TOOLS)
    placeholders = _agent()["dynamic_variables"]["dynamic_variable_placeholders"]

    assert len(TOOLS) == 11
    assert sorted(test["tool_mock_config"]["mocked_tool_ids"]) == tool_vars
    assert sorted(test["tool_mock_overrides"]) == tool_vars
    assert test["tool_mock_config"]["fallback_strategy"] == "raise_error"
    assert set(test["dynamic_variables"]) == set(placeholders)
    assert test["dynamic_variables"]["rejected"] is False
