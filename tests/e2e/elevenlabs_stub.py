"""ElevenLabs' conversation-audio API for the Playwright specs (no ElevenLabs account needed).

`GET /v1/convai/conversations/<id>/audio` with the e2e `xi-api-key` answers a 3-second WAV tone
for any conversation id starting `conv_e2e_`, 404 for any other id, 401 for a wrong key.
Started by frontend/playwright.config.ts; the backend under test points ELEVENLABS_API_BASE here.

Usage: python elevenlabs_stub.py <port> <api key>
"""

import io
import math
import re
import struct
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AUDIO_PATH = re.compile(r"^/v1/convai/conversations/([^/]+)/audio$")


def tone(seconds: float = 3.0, rate: int = 8000) -> bytes:
    """A 440 Hz mono 16-bit PCM WAV (plays in any browser, unlike mp3 in some Chromium builds)."""
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(seconds * rate))
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return out.getvalue()


def serve(port: int, api_key: str) -> None:
    audio = tone()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            if self.path == "/healthz":
                self._send(200, "text/plain", b"ok")
                return
            match = AUDIO_PATH.match(self.path)
            if match is None:
                self._send(404, "application/json", b'{"detail":"not found"}')
            elif self.headers.get("xi-api-key") != api_key:
                self._send(401, "application/json", b'{"detail":"invalid api key"}')
            elif not match.group(1).startswith("conv_e2e_"):
                self._send(404, "application/json", b'{"detail":"no audio"}')
            else:
                self._send(200, "audio/wav", audio)

        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2])
