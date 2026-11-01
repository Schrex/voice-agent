"""backend/agent/push.py: make an ElevenLabs agent (and its tests) match the repo (ticket #5).

ElevenLabs is replaced by `FakeElevenLabs`, an in-memory stand-in for the agent and
agent-testing endpoints served through `httpx.MockTransport`. Like the real API it returns
more fields than we send (server defaults), so push.py must diff by subset, not equality.
"""

import copy
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent.push import AGENT_DIR, PushError, main, push

ENV = {
    "agent_name": "Field Request Assistant (test)",
    "backend_url": "https://backend.example.test",
    "hook_secret_id": "secret_hook_0001",
    "tool_secret_id": "secret_tool_0001",
}

# Fields the real API fills in on its own; push.py must not treat them as drift.
SERVER_AGENT_DEFAULTS: dict[str, Any] = {
    "conversation_config": {
        "tts": {"stability": 0.5, "speed": 1.0},
        "turn": {"turn_timeout": 7.0},
        "agent": {"prompt": {"temperature": 0.0, "tool_ids": []}},
    },
    "platform_settings": {"privacy": {"record_voice": True}},
    "metadata": {"created_at_unix_secs": 1_790_000_000},
}
SERVER_TEST_DEFAULTS: dict[str, Any] = {"parent_folder_id": None, "environment": "production"}
SERVER_TOOL_DEFAULTS: dict[str, Any] = {
    "tool_config": {"response_timeout_secs": 20, "disable_interruptions": False},
    "access_info": {"is_creator": True},
    "usage_stats": {"avg_latency_secs": 0.0},
}


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class FakeElevenLabs:
    def __init__(self) -> None:
        self.agents: dict[str, dict[str, Any]] = {}
        self.tests: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.api_keys: set[str] = set()

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.elevenlabs.io",
            transport=httpx.MockTransport(self.handle),
            headers={"xi-api-key": "test-key"},
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.api_keys.add(request.headers.get("xi-api-key", ""))
        path, method = request.url.path, request.method
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if method in {"POST", "PATCH", "PUT", "DELETE"}:
            self.writes.append(f"{method} {path}")

        if path == "/v1/convai/agents" and method == "GET":
            return self._search(request, self.agents, "agents", "agent_id")
        if path == "/v1/convai/agents/create" and method == "POST":
            agent_id = f"agent_{len(self.agents) + 1:04d}"
            self.agents[agent_id] = _merge(SERVER_AGENT_DEFAULTS, body)
            return httpx.Response(200, json={"agent_id": agent_id})
        if m := re.fullmatch(r"/v1/convai/agents/([^/]+)", path):
            agent_id = m.group(1)
            if agent_id not in self.agents:
                return httpx.Response(404, json={"detail": "not found"})
            if method == "PATCH":
                self.agents[agent_id] = _merge(self.agents[agent_id], body)
            return httpx.Response(200, json={"agent_id": agent_id, **self.agents[agent_id]})

        if path == "/v1/convai/agent-testing" and method == "GET":
            return self._search(request, self.tests, "tests", "id")
        if path == "/v1/convai/agent-testing/create" and method == "POST":
            test_id = f"test_{len(self.tests) + 1:04d}"
            self.tests[test_id] = {**SERVER_TEST_DEFAULTS, **body}
            return httpx.Response(200, json={"id": test_id})
        if m := re.fullmatch(r"/v1/convai/agent-testing/([^/]+)", path):
            test_id = m.group(1)
            if test_id not in self.tests:
                return httpx.Response(404, json={"detail": "not found"})
            if method == "PUT":
                self.tests[test_id] = {**SERVER_TEST_DEFAULTS, **body}
            return httpx.Response(200, json={"id": test_id, **self.tests[test_id]})

        if path == "/v1/convai/tools" and method == "GET":
            # The list holds full tool objects; the name is inside tool_config.
            needle = request.url.params.get("search", "").lower()
            found = [
                {"id": tool_id, **tool}
                for tool_id, tool in self.tools.items()
                if needle in tool["tool_config"]["name"].lower()
            ]
            return httpx.Response(200, json={"tools": found, "has_more": False})
        if path == "/v1/convai/tools" and method == "POST":
            tool_id = f"tool_{len(self.tools) + 1:04d}"
            self.tools[tool_id] = _merge(SERVER_TOOL_DEFAULTS, body)
            return httpx.Response(200, json={"id": tool_id, **self.tools[tool_id]})
        if m := re.fullmatch(r"/v1/convai/tools/([^/]+)", path):
            tool_id = m.group(1)
            if tool_id not in self.tools:
                return httpx.Response(404, json={"detail": "not found"})
            if method == "PATCH":
                self.tools[tool_id] = _merge(self.tools[tool_id], body)
            return httpx.Response(200, json={"id": tool_id, **self.tools[tool_id]})
        return httpx.Response(404, json={"detail": f"no route {method} {path}"})

    @staticmethod
    def _search(
        request: httpx.Request, items: dict[str, dict[str, Any]], key: str, id_field: str
    ) -> httpx.Response:
        # Substring search, like the real `search` parameter: callers must match names exactly.
        needle = request.url.params.get("search", "")
        found = [
            {id_field: item_id, "name": item["name"], "type": item.get("type")}
            for item_id, item in items.items()
            if needle.lower() in item["name"].lower()
        ]
        return httpx.Response(200, json={key: found, "has_more": False, "next_cursor": None})


@pytest.fixture
def el() -> FakeElevenLabs:
    return FakeElevenLabs()


def test_first_push_creates_the_agent_and_second_push_changes_nothing(
    el: FakeElevenLabs,
) -> None:
    first = push(ENV, el.client())
    assert len(el.agents) == 1
    assert any("created" in line for line in first)

    el.writes.clear()
    second = push(ENV, el.client())

    assert el.writes == []
    assert second[-1] == "No changes."


def test_push_creates_the_submit_requests_tool_pointing_at_the_env_backend(
    el: FakeElevenLabs,
) -> None:
    push(ENV, el.client())

    (tool,) = el.tools.values()
    config = tool["tool_config"]
    assert config["type"] == "webhook"
    assert config["name"] == "submit_requests"
    assert config["api_schema"]["url"] == "https://backend.example.test/tools/submit_requests"
    assert config["api_schema"]["method"] == "POST"
    assert config["api_schema"]["request_headers"] == {
        "X-Tool-Secret": {"secret_id": "secret_tool_0001"},
        "X-Conversation-Id": {"variable_name": "system__conversation_id"},
    }


def test_pushed_agent_uses_the_created_tool_by_id(el: FakeElevenLabs) -> None:
    push(ENV, el.client())

    (tool_id,) = el.tools
    (agent,) = el.agents.values()
    assert agent["conversation_config"]["agent"]["prompt"]["tool_ids"] == [tool_id]


def test_tests_that_mock_submit_requests_reference_the_created_tool_id(
    el: FakeElevenLabs,
) -> None:
    push(ENV, el.client())

    (tool_id,) = el.tools
    mocking = [t for t in el.tests.values() if t.get("tool_mock_config")]
    assert mocking
    for test in mocking:
        assert test["tool_mock_config"]["mocked_tool_ids"] == [tool_id]
        assert list(test["tool_mock_overrides"]) == [tool_id]
    referencing = [t for t in el.tests.values() if t.get("type") == "tool"]
    assert {t["tool_call_parameters"]["referenced_tool"]["id"] for t in referencing} >= {tool_id}
    assert not any("${" in json.dumps(t) for t in el.tests.values())


def test_edit_to_the_tool_in_the_web_ui_is_overwritten_then_stable(el: FakeElevenLabs) -> None:
    push(ENV, el.client())
    (tool_id,) = el.tools
    el.tools[tool_id]["tool_config"]["api_schema"]["url"] = "https://elsewhere.example.test/x"
    el.writes.clear()

    lines = push(ENV, el.client())

    assert el.writes == [f"PATCH /v1/convai/tools/{tool_id}"]
    assert "tool_config.api_schema.url" in lines[0]
    el.writes.clear()
    assert push(ENV, el.client())[-1] == "No changes."
    assert el.writes == []


def test_push_creates_each_repo_test_by_name(el: FakeElevenLabs) -> None:
    push(ENV, el.client())

    assert sorted(t["name"] for t in el.tests.values()) == [
        "AC1.1 first utterance identifies as automated and discloses recording",
        "AC1.2 does not submit before the read-back is confirmed",
        "AC1.2 reads back Job, quantity, unit and time before asking to submit",
        "AC1.7 says recorded and not yet confirmed and gives the reference",
        "AC1.8 does not submit when the foreman leaves before confirming",
        "AC8.1 unrostered caller: call ends after the rejection line",
        "AC8.1 unrostered caller: no Job or Request information disclosed",
        "J1 asks at most one question per turn",
        "J1 quantity corrected during read-back is the value submitted",
    ]


def test_pushed_agent_points_its_call_start_webhook_at_the_env_backend(
    el: FakeElevenLabs,
) -> None:
    push(ENV, el.client())

    (agent,) = el.agents.values()
    assert agent["name"] == "Field Request Assistant (test)"
    webhook = agent["platform_settings"]["workspace_overrides"][
        "conversation_initiation_client_data_webhook"
    ]
    assert webhook == {
        "url": "https://backend.example.test/hooks/call-start",
        "request_headers": {"X-Hook-Secret": {"secret_id": "secret_hook_0001"}},
    }
    assert (
        agent["conversation_config"]["agent"]["prompt"]["prompt"]
        == (AGENT_DIR / "prompt.md").read_text()
    )


def test_edit_made_in_the_web_ui_is_overwritten_then_stable(el: FakeElevenLabs) -> None:
    push(ENV, el.client())
    (agent_id,) = el.agents
    el.agents[agent_id]["conversation_config"]["agent"]["first_message"] = "Hello there!"
    el.writes.clear()

    lines = push(ENV, el.client())

    assert el.writes == [f"PATCH /v1/convai/agents/{agent_id}"]
    (agent_line,) = [line for line in lines if line.startswith("agent ")]
    assert "conversation_config.agent.first_message" in agent_line
    assert lines[-1] == "1 change(s)."
    assert el.agents[agent_id]["conversation_config"]["agent"]["first_message"].startswith(
        "Hi {{foreman_first_name}}"
    )
    el.writes.clear()
    assert push(ENV, el.client())[-1] == "No changes."
    assert el.writes == []


def test_changed_remote_test_is_replaced(el: FakeElevenLabs) -> None:
    push(ENV, el.client())
    test_id = next(i for i, t in el.tests.items() if t["type"] == "llm")
    el.tests[test_id]["success_condition"] = "anything goes"
    el.writes.clear()

    push(ENV, el.client())

    assert el.writes == [f"PUT /v1/convai/agent-testing/{test_id}"]
    assert el.tests[test_id]["success_condition"] != "anything goes"


def test_agent_is_matched_by_exact_name_only(el: FakeElevenLabs) -> None:
    el.agents["agent_other"] = {"name": "Field Request Assistant (test) old copy"}

    push(ENV, el.client())

    assert el.agents["agent_other"] == {"name": "Field Request Assistant (test) old copy"}
    assert "POST /v1/convai/agents/create" in el.writes


def test_two_agents_with_the_same_name_is_an_error(el: FakeElevenLabs) -> None:
    el.agents["agent_a"] = {"name": ENV["agent_name"]}
    el.agents["agent_b"] = {"name": ENV["agent_name"]}

    with pytest.raises(PushError, match="2 objects named"):
        push(ENV, el.client())
    assert not any("/agents" in write for write in el.writes)


@pytest.fixture
def agent_dir(tmp_path: Path) -> Path:
    """A copy of backend/agent whose `staging` env is provisioned and `local` is not."""
    for name in ("agent.json", "prompt.md"):
        (tmp_path / name).write_text((AGENT_DIR / name).read_text())
    for sub in ("tests", "tools"):
        (tmp_path / sub).mkdir(exist_ok=True)
        for path in (AGENT_DIR / sub).glob("*.json"):
            (tmp_path / sub / path.name).write_text(path.read_text())
    envs = {"staging": ENV, "local": {**ENV, "backend_url": None}}
    (tmp_path / "envs.json").write_text(json.dumps(envs))
    return tmp_path


def test_cli_prints_one_line_per_object_and_exits_0(
    el: FakeElevenLabs, agent_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--env", "staging"], client=el.client(), agent_dir=agent_dir) == 0
    assert main(["--env", "staging"], client=el.client(), agent_dir=agent_dir) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[:2] == [
        "tool 'submit_requests': created (tool_0001)",
        "agent 'Field Request Assistant (test)': created (agent_0001)",
    ]
    second = out[len(out) // 2 :]
    assert second[:2] == [
        "tool 'submit_requests': unchanged",
        "agent 'Field Request Assistant (test)': unchanged",
    ]
    assert len(second) == 2 + len(list((agent_dir / "tests").glob("*.json"))) + 1
    assert all(line.startswith("test '") and line.endswith("': unchanged") for line in second[2:-1])
    assert second[-1] == "No changes."


def test_cli_refuses_an_env_with_unset_values_and_sends_nothing(
    el: FakeElevenLabs, agent_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--env", "local"], client=el.client(), agent_dir=agent_dir) == 1

    assert "backend_url" in capsys.readouterr().err
    assert el.writes == [] and el.api_keys == set()


def test_cli_without_api_key_exits_1(
    agent_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    assert main(["--env", "staging"], agent_dir=agent_dir) == 1
    assert "ELEVENLABS_API_KEY" in capsys.readouterr().err


def test_api_error_is_reported_without_the_api_key(
    agent_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def deny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api key"})

    client = httpx.Client(
        base_url="https://api.elevenlabs.io",
        transport=httpx.MockTransport(deny),
        headers={"xi-api-key": "sk-very-secret"},
    )
    assert main(["--env", "staging"], client=client, agent_dir=agent_dir) == 1
    err = capsys.readouterr().err
    assert "401" in err and "sk-very-secret" not in err
