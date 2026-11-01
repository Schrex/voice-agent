"""Make an environment's ElevenLabs agent and agent tests match `backend/agent/`.

Usage (from `backend/`, with `ELEVENLABS_API_KEY` set):

    uv run python -m agent.push --env staging

Idempotent: each object is read first and written only when it differs from the repo, so a
second run reports "No changes." and sends no writes. Remote objects carry server defaults we
never send, so "differs" means a value we set is missing or different (subset comparison).

- Agent: `agent.json` with `${...}` filled from `envs.json[env]` and `prompt.md` as the
  system prompt. Found by its exact name; created if absent, else PATCHed.
- Tests: every `tests/*.json` (ElevenLabs agent-testing bodies). Found by exact name; created
  if absent, else replaced with PUT. Tests are workspace objects, shared by all agents there.

Edits made in the ElevenLabs web UI to fields we set are overwritten (AGENTS.md).
"""

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from string import Template
from typing import Any

import httpx

AGENT_DIR = Path(__file__).resolve().parent
API_BASE = "https://api.elevenlabs.io"
ENV_KEYS = ("agent_name", "backend_url", "hook_secret_id")


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


def _fill(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        return Template(node).substitute(values)
    if isinstance(node, dict):
        return {key: _fill(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_fill(item, values) for item in node]
    return node


def desired_agent(env: dict[str, str], agent_dir: Path = AGENT_DIR) -> dict[str, Any]:
    """The agent body this env should have: agent.json filled in, prompt.md as the prompt."""
    body: dict[str, Any] = _fill(json.loads((agent_dir / "agent.json").read_text()), env)
    prompt = body["conversation_config"]["agent"].setdefault("prompt", {})
    prompt["prompt"] = (agent_dir / "prompt.md").read_text()
    return body


def desired_tests(agent_dir: Path = AGENT_DIR) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted((agent_dir / "tests").glob("*.json"))]


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


def _find_by_name(client: httpx.Client, url: str, key: str, id_field: str, name: str) -> str | None:
    ids = [item[id_field] for item in _pages(client, url, key, name) if item["name"] == name]
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
) -> str:
    name = body["name"]
    object_id = _find_by_name(client, list_url, list_key, id_field, name)
    if object_id is None:
        created = _check(client.post(create_url, json=body))
        return f"{kind} {name!r}: created ({created[id_field]})"
    url = f"{item_url}/{object_id}"
    changed = drift(body, _check(client.get(url)))
    if not changed:
        return f"{kind} {name!r}: unchanged"
    _check(client.request(update_method, url, json=body))
    return f"{kind} {name!r}: updated {', '.join(changed)}"


def push(env: dict[str, str], client: httpx.Client, agent_dir: Path = AGENT_DIR) -> list[str]:
    """Sync the agent and the tests; return one line per object, then a summary line."""
    lines = [
        _sync(
            client,
            kind="agent",
            body=desired_agent(env, agent_dir),
            list_url="/v1/convai/agents",
            list_key="agents",
            id_field="agent_id",
            create_url="/v1/convai/agents/create",
            item_url="/v1/convai/agents",
            update_method="PATCH",
        )
    ]
    for test in desired_tests(agent_dir):
        lines.append(
            _sync(
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
        )
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
