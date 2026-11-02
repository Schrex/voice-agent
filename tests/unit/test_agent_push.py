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


def _tool_id(el: FakeElevenLabs, name: str) -> str:
    (tool_id,) = [i for i, t in el.tools.items() if t["tool_config"]["name"] == name]
    return tool_id


@pytest.mark.parametrize(
    "name",
    [
        "add_note",
        "amend_request",
        "create_callback_request",
        "find_duplicates",
        "find_jobs",
        "find_open_requests",
        "resolve_needed_by",
        "start_emergency",
        "submit_requests",
        "transfer_to_office",
        "withdraw_request",
    ],
)
def test_push_creates_each_tool_pointing_at_the_env_backend(el: FakeElevenLabs, name: str) -> None:
    push(ENV, el.client())

    assert len(el.tools) == 11
    config = el.tools[_tool_id(el, name)]["tool_config"]
    assert config["type"] == "webhook"
    assert config["api_schema"]["url"] == f"https://backend.example.test/tools/{name}"
    assert config["api_schema"]["method"] == "POST"
    assert config["api_schema"]["request_headers"] == {
        "X-Tool-Secret": {"secret_id": "secret_tool_0001"},
        "X-Conversation-Id": {"variable_name": "system__conversation_id"},
    }


def test_pushed_agent_uses_the_created_tools_by_id(el: FakeElevenLabs) -> None:
    push(ENV, el.client())

    (agent,) = el.agents.values()
    assert agent["conversation_config"]["agent"]["prompt"]["tool_ids"] == [
        _tool_id(el, "find_jobs"),
        _tool_id(el, "resolve_needed_by"),
        _tool_id(el, "submit_requests"),
        _tool_id(el, "find_open_requests"),
        _tool_id(el, "create_callback_request"),
        _tool_id(el, "add_note"),
        _tool_id(el, "transfer_to_office"),
        _tool_id(el, "find_duplicates"),
        _tool_id(el, "amend_request"),
        _tool_id(el, "start_emergency"),
        _tool_id(el, "withdraw_request"),
    ]


def test_tests_that_mock_the_tools_reference_the_created_tool_ids(
    el: FakeElevenLabs,
) -> None:
    push(ENV, el.client())

    tool_ids = sorted(el.tools)
    mocking = [t for t in el.tests.values() if t.get("tool_mock_config")]
    assert mocking
    for test in mocking:
        # Every simulation that can reach a tool mocks both, so it never writes to a backend.
        assert sorted(test["tool_mock_config"]["mocked_tool_ids"]) == tool_ids
        assert sorted(test["tool_mock_overrides"]) == tool_ids
    referencing = [t for t in el.tests.values() if t.get("type") == "tool"]
    assert {t["tool_call_parameters"]["referenced_tool"]["id"] for t in referencing} >= {
        _tool_id(el, "submit_requests")
    }
    assert not any("${" in json.dumps(t) for t in el.tests.values())


def test_edit_to_the_tool_in_the_web_ui_is_overwritten_then_stable(el: FakeElevenLabs) -> None:
    push(ENV, el.client())
    tool_id = _tool_id(el, "submit_requests")
    el.tools[tool_id]["tool_config"]["api_schema"]["url"] = "https://elsewhere.example.test/x"
    el.writes.clear()

    lines = push(ENV, el.client())

    assert el.writes == [f"PATCH /v1/convai/tools/{tool_id}"]
    (tool_line,) = [line for line in lines if line.startswith("tool 'submit_requests'")]
    assert "tool_config.api_schema.url" in tool_line
    el.writes.clear()
    assert push(ENV, el.client())[-1] == "No changes."
    assert el.writes == []


def test_push_creates_each_repo_test_by_name(el: FakeElevenLabs) -> None:
    push(ENV, el.client())

    assert sorted(t["name"] for t in el.tests.values()) == [
        "AC1.1 first utterance identifies as automated and discloses recording",
        "AC1.2 does not submit before the read-back is confirmed",
        "AC1.2 needed-by is read back as the weekday and time the backend resolved",
        "AC1.2 reads back Job, quantity, unit and time before asking to submit",
        "AC1.3 a Job alias is read back as the canonical Job name",
        "AC1.4 an unknown Job is read back as said, never as a listed Job",
        "AC1.4 an unknown Job is submitted as Unmatched without a job_id",
        "AC1.5 an unknown needed-by is submitted without needed_by_spoken",
        "AC1.5 needed-by asked once, then recorded without it when the Foreman cannot say",
        "AC1.6 two confirmed needs are submitted together as two items",
        "AC1.6 two needs in one utterance get a numbered summary, one confirmation and both "
        "references",
        "AC1.7 says recorded and not yet confirmed and gives the reference",
        "AC1.8 does not submit when the foreman leaves before confirming",
        "AC2.1 a new truck request on the same Job asks whether it is about the open one",
        "AC2.2 yes, it is about that request: a note on it and no new request",
        "AC3.1 a Recorded request: the office has not picked it up yet",
        "AC3.2 an Acknowledged request: names Dispatch and says it is not confirmed",
        "AC3.3 a Resolved/Denied request: says it was denied and reads the explanation",
        "AC3.4 accepting the Callback offer after no match records a Callback Request",
        "AC3.4 no matching request: says it cannot find one and offers Transfer or Callback",
        'AC3.5 "need an answer today" is an urgent note on the existing request, not a new one',
        "AC4.1 cancelling a Recorded request withdraws it after a yes and says so",
        "AC4.2 a new time for an In Progress request is flagged for the office, not changed",
        "AC5.1 mid-intake get me the office: transfers at once without asking why",
        "AC5.4 Callback Request recorded after a yes, with no callback time promised",
        "AC5.4 Callback Request without a reason: asked once, then recorded",
        "AC5.4 the reason is sent as the Foreman said it, after the yes",
        'AC6.1 "I just want the office, there\'s a gas leak" is an Emergency, not a plain Transfer',
        "AC6.1 gas line mid-intake: the safety line comes before any other question",
        "AC6.2/AC6.3 Emergency is recorded, then the call is transferred after the safety line",
        "AC6.4 Emergency: never says help is coming or that anyone was reached",
        "AC8.1 unrostered caller: call ends after the rejection line",
        "AC8.1 unrostered caller: no Job or Request information disclosed",
        'ACX.1 "do you have a mini ex free Thursday?" is not answered; it is recorded as '
        "Information",
        'ACX.1 "is the truck coming?" right after a submit: recorded, not confirmed, no arrival '
        "time",
        'ACX.1 "just tell me you\'ve got one" during intake: no availability, the read-back '
        "goes on",
        "ACX.1 Callback Request pressed for who will call and when: neither is promised",
        "ACX.1 a Denied request pressed to approve it anyway: reads the explanation, decides "
        "nothing",
        "ACX.1 a Recorded request pressed for a yes: the office has not picked it up, nothing "
        "approved",
        'ACX.1 a change flagged, not applied, pressed with "so Thursday\'s fine?": nothing decided',
        'ACX.1 after an urgent note, "so I\'ll hear back today?": no answer or time promised',
        'ACX.1 an Acknowledged request pressed for "a ballpark": names the Owner, gives no time',
        "ACX.1 status lookup: never states availability, ETA or an unrecorded decision",
        'ACX.2 "hey, how you doing?": the agent does not ask back about the day or mood',
        'ACX.2 "we\'re two days behind": the agent asks nothing about progress or productivity',
        'ACX.2 "what a day, everything\'s going sideways": the agent asks nothing about the day',
        "ACX.2 a status call that ends: no question about the day, mood or how the job is going",
        "J1 a need dropped during the numbered summary is not submitted",
        "J1 asks at most one question per turn",
        "J1 quantity corrected during read-back is the value submitted",
        "J1 work stopped, needed right now: the urgency Today is stated back",
        "J2 no, it is a new one: a new request is submitted",
        "J3 step 2: several matching requests, asks which one by need and Job",
        "J4 withdrawing an In Progress request is flagged for the office, not withdrawn",
        "J5 transfers even when the office could not be told",
        "J5 with no Office Line says the test line and hangs up",
        "J6 transfers even when the Emergency could not be recorded",
        "J6 with no Office Line gives the safety line, records it, then the test line",
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
    assert out[:12] == [
        "tool 'add_note': created (tool_0001)",
        "tool 'amend_request': created (tool_0002)",
        "tool 'create_callback_request': created (tool_0003)",
        "tool 'find_duplicates': created (tool_0004)",
        "tool 'find_jobs': created (tool_0005)",
        "tool 'find_open_requests': created (tool_0006)",
        "tool 'resolve_needed_by': created (tool_0007)",
        "tool 'start_emergency': created (tool_0008)",
        "tool 'submit_requests': created (tool_0009)",
        "tool 'transfer_to_office': created (tool_0010)",
        "tool 'withdraw_request': created (tool_0011)",
        "agent 'Field Request Assistant (test)': created (agent_0001)",
    ]
    second = out[len(out) // 2 :]
    assert second[:12] == [
        "tool 'add_note': unchanged",
        "tool 'amend_request': unchanged",
        "tool 'create_callback_request': unchanged",
        "tool 'find_duplicates': unchanged",
        "tool 'find_jobs': unchanged",
        "tool 'find_open_requests': unchanged",
        "tool 'resolve_needed_by': unchanged",
        "tool 'start_emergency': unchanged",
        "tool 'submit_requests': unchanged",
        "tool 'transfer_to_office': unchanged",
        "tool 'withdraw_request': unchanged",
        "agent 'Field Request Assistant (test)': unchanged",
    ]
    assert len(second) == 12 + len(list((agent_dir / "tests").glob("*.json"))) + 1
    assert all(
        line.startswith("test '") and line.endswith("': unchanged") for line in second[12:-1]
    )
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
