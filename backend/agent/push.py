"""Make an environment's ElevenLabs agent and agent tests match `backend/agent/`.

Usage (from `backend/`, with `ELEVENLABS_API_KEY` set):

    uv run python -m agent.push --env staging

Idempotent: each object is read first and written only when it differs from the repo, so a
second run reports "No changes." and sends no writes. Remote objects carry server defaults we
never send, so "differs" means a value we set is missing or different (subset comparison).

- Tools: every `tools/*.json` (ElevenLabs workspace tool bodies, `${...}` filled from
  `envs.json[env]`). Found by the exact `tool_config.name`; created if absent, else PATCHed.
  Synced first, because the agent and the tests refer to them by id.
- Agent: `agent.json` with `${...}` filled from `envs.json[env]` and the tool ids
  (`${tool_<name>}`), and `prompt.md` as the system prompt. Found by its exact name; created
  if absent, else PATCHed.
- Tests: every `tests/*.json` (ElevenLabs agent-testing bodies), `${tool_<name>}` filled.
  Found by exact name; created if absent, else replaced with PUT. Tests are workspace objects,
  shared by all agents there.

Edits made in the ElevenLabs web UI to fields we set are overwritten (AGENTS.md).
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any

import httpx

AGENT_DIR = Path(__file__).resolve().parent
API_BASE = "https://api.elevenlabs.io"
ENV_KEYS = ("agent_name", "backend_url", "hook_secret_id", "tool_secret_id")


class PushError(Exception):
    """A problem the operator must fix; printed without a traceback."""


def load_env(name: str, agent_dir: Path = AGENT_DIR) -> dict[str, str]:
    envs: dict[str, dict[str, str | None]] = json.loads((agent_dir / "envs.json").read_text())
    if name not in envs:
        raise PushError(f"unknown env {name!r}; expected one of {sorted(envs)}")
    values = envs[name]
    missing = [key for key in ENV_KEYS if not values.get(key)]
    if missing:
        raise PushError(f"envs.json {name}: set {', '.join(missing)} before pushing")
    return {key: str(values[key]) for key in ENV_KEYS}


def safety_line(agent_dir: Path = AGENT_DIR) -> str:
    """The Emergency safety line (spec J6 step 2): `safety_line.txt` without its `#` comment
    lines. The prompt must say exactly this; the agent config tests check it does."""
    lines = (agent_dir / "safety_line.txt").read_text().splitlines()
    return "\n".join(line for line in lines if not line.startswith("#")).strip()


def _fill(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        return Template(node).substitute(values)
    if isinstance(node, dict):
        return {_fill(key, values): _fill(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_fill(item, values) for item in node]
    return node


def _tool_values(tool_ids: Mapping[str, str]) -> dict[str, str]:
    """`${tool_<name>}` placeholders for the workspace tool ids, keyed by tool name."""
    return {f"tool_{name}": tool_id for name, tool_id in tool_ids.items()}


def _load_dir(agent_dir: Path, sub: str, values: dict[str, str]) -> list[dict[str, Any]]:
    return [
        _fill(json.loads(path.read_text()), values)
        for path in sorted((agent_dir / sub).glob("*.json"))
    ]


def desired_tools(env: dict[str, str], agent_dir: Path = AGENT_DIR) -> list[dict[str, Any]]:
    """The workspace tool bodies this env should have: tools/*.json filled in."""
    return _load_dir(agent_dir, "tools", env)


def desired_agent(
    env: dict[str, str], tool_ids: Mapping[str, str], agent_dir: Path = AGENT_DIR
) -> dict[str, Any]:
    """The agent body this env should have: agent.json filled in, prompt.md as the prompt."""
    values = {**env, **_tool_values(tool_ids)}
    body: dict[str, Any] = _fill(json.loads((agent_dir / "agent.json").read_text()), values)
    prompt = body["conversation_config"]["agent"].setdefault("prompt", {})
    prompt["prompt"] = (agent_dir / "prompt.md").read_text()
    return body


def desired_tests(tool_ids: Mapping[str, str], agent_dir: Path = AGENT_DIR) -> list[dict[str, Any]]:
    return _load_dir(agent_dir, "tests", _tool_values(tool_ids))


def drift(desired: Any, remote: Any, path: str = "") -> list[str]:
    """Paths where `remote` lacks or contradicts a value in `desired`; [] if it contains it."""
    if isinstance(desired, dict):
        if not isinstance(remote, dict):
            return [path or "."]
        return [
            p
            for key, value in desired.items()
            for p in drift(value, remote.get(key), f"{path}.{key}" if path else key)
        ]
    if isinstance(desired, list):
        if not isinstance(remote, list) or len(remote) != len(desired):
            return [path]
        return [
            p
            for i, (d, r) in enumerate(zip(desired, remote, strict=True))
            for p in drift(d, r, f"{path}[{i}]")
        ]
    return [] if desired == remote else [path]


def _check(response: httpx.Response) -> Any:
    if response.is_error:
        raise PushError(
            f"{response.request.method} {response.request.url.path} -> "
            f"{response.status_code}: {response.text[:500]}"
        )
    return response.json()


def _pages(client: httpx.Client, url: str, key: str, search: str) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"search": search, "page_size": 100}
        if cursor:
            params["cursor"] = cursor
        page = _check(client.get(url, params=params))
        yield from page[key]
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            return


def _name(item: dict[str, Any]) -> str:
    return str(item["name"])


def _tool_name(item: dict[str, Any]) -> str:
    return str(item["tool_config"]["name"])


def _find_by_name(
    client: httpx.Client,
    url: str,
    key: str,
    id_field: str,
    name: str,
    name_of: Callable[[dict[str, Any]], str],
) -> str | None:
    ids = [item[id_field] for item in _pages(client, url, key, name) if name_of(item) == name]
    if len(ids) > 1:
        raise PushError(f"{len(ids)} objects named {name!r} at {url}; delete the extras")
    return ids[0] if ids else None


def _sync(
    client: httpx.Client,
    *,
    kind: str,
    body: dict[str, Any],
    list_url: str,
    list_key: str,
    id_field: str,
    create_url: str,
    item_url: str,
    update_method: str,
    name_of: Callable[[dict[str, Any]], str] = _name,
) -> tuple[str, str]:
    """Create or update one object; return its id and a report line."""
    name = name_of(body)
    object_id = _find_by_name(client, list_url, list_key, id_field, name, name_of)
    if object_id is None:
        created_id = str(_check(client.post(create_url, json=body))[id_field])
        return created_id, f"{kind} {name!r}: created ({created_id})"
    url = f"{item_url}/{object_id}"
    changed = drift(body, _check(client.get(url)))
    if not changed:
        return object_id, f"{kind} {name!r}: unchanged"
    _check(client.request(update_method, url, json=body))
    return object_id, f"{kind} {name!r}: updated {', '.join(changed)}"


def push(env: dict[str, str], client: httpx.Client, agent_dir: Path = AGENT_DIR) -> list[str]:
    """Sync tools, agent and tests; return one line per object, then a summary line."""
    lines: list[str] = []
    tool_ids: dict[str, str] = {}
    for tool in desired_tools(env, agent_dir):
        tool_id, line = _sync(
            client,
            kind="tool",
            body=tool,
            list_url="/v1/convai/tools",
            list_key="tools",
            id_field="id",
            create_url="/v1/convai/tools",
            item_url="/v1/convai/tools",
            update_method="PATCH",
            name_of=_tool_name,
        )
        tool_ids[_tool_name(tool)] = tool_id
        lines.append(line)
    _, line = _sync(
        client,
        kind="agent",
        body=desired_agent(env, tool_ids, agent_dir),
        list_url="/v1/convai/agents",
        list_key="agents",
        id_field="agent_id",
        create_url="/v1/convai/agents/create",
        item_url="/v1/convai/agents",
        update_method="PATCH",
    )
    lines.append(line)
    for test in desired_tests(tool_ids, agent_dir):
        _, line = _sync(
            client,
            kind="test",
            body=test,
            list_url="/v1/convai/agent-testing",
            list_key="tests",
            id_field="id",
            create_url="/v1/convai/agent-testing/create",
            item_url="/v1/convai/agent-testing",
            update_method="PUT",
        )
        lines.append(line)
    changed = sum(not line.endswith(": unchanged") for line in lines)
    lines.append(f"{changed} change(s)." if changed else "No changes.")
    return lines


def main(
    argv: Sequence[str] | None = None,
    client: httpx.Client | None = None,
    agent_dir: Path = AGENT_DIR,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.push", description=__doc__)
    parser.add_argument("--env", required=True, choices=["local", "staging", "prod"])
    args = parser.parse_args(argv)
    try:
        env = load_env(args.env, agent_dir)
        if client is None:
            api_key = os.environ.get("ELEVENLABS_API_KEY")
            if not api_key:
                raise PushError("ELEVENLABS_API_KEY is not set")
            client = httpx.Client(
                base_url=os.environ.get("ELEVENLABS_API_BASE") or API_BASE,
                headers={"xi-api-key": api_key},
                timeout=30,
            )
        with client:
            for line in push(env, client, agent_dir):
                print(line)
    except PushError as exc:
        print(f"push failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
