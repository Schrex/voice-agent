"""ElevenLabs conversation audio (`GET /v1/convai/conversations/{id}/audio`).

Recordings stay in ElevenLabs (architecture §3.4); the dashboard gets them only through the
backend, which streams ElevenLabs' response through without storing it.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

import httpx


class RecordingNotFound(Exception):
    """ElevenLabs has no audio for the conversation (never recorded, or past retention)."""


class RecordingUnavailable(Exception):
    """ElevenLabs could not be asked, or answered with an error."""


@dataclass(frozen=True)
class Recording:
    content_type: str
    chunks: Iterator[bytes]
    """The audio bytes as they arrive; reading to the end (or closing it) ends the request."""


class ElevenLabsAudio:
    def __init__(self, client: httpx.Client, api_key: str | None) -> None:
        self._client = client
        self._api_key = api_key

    def open(self, conversation_id: str) -> Recording:
        """Start streaming the conversation's audio. Raises before any byte is passed on."""
        if not self._api_key:
            raise RecordingUnavailable("ELEVENLABS_API_KEY is not set")
        request = self._client.build_request(
            "GET",
            f"/v1/convai/conversations/{quote(conversation_id, safe='')}/audio",
            headers={"xi-api-key": self._api_key},
        )
        try:
            response = self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise RecordingUnavailable(type(exc).__name__) from exc
        if response.status_code == 404:
            response.close()
            raise RecordingNotFound(conversation_id)
        if response.is_error:
            response.close()
            raise RecordingUnavailable(f"ElevenLabs answered {response.status_code}")
        return Recording(
            content_type=response.headers.get("content-type", "audio/mpeg"),
            chunks=_stream(response),
        )


def _stream(response: httpx.Response) -> Iterator[bytes]:
    try:
        yield from response.iter_bytes()
    finally:
        response.close()
