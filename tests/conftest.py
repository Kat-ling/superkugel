"""Gemeinsame Test-Hilfen: Alexa-Requests, MP3-Testdateien, gefälschte Abhängigkeiten."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from superkugel.app import build_skill, handle_event  # noqa: E402
from superkugel.audiobooks.models import Book, Chapter  # noqa: E402
from superkugel.config import Settings  # noqa: E402
from superkugel.conversation.llm import LlmError, OpenAIClient  # noqa: E402
from superkugel.handlers.common import Services  # noqa: E402
from superkugel.services.ops import Mode  # noqa: E402
from superkugel.services.storage import MemoryStore  # noqa: E402

USER = "amzn1.ask.account.TESTUSER"
DEVICE = "dev1"


# ---------------------------------------------------------------- MP3-Testdateien
def make_mp3(path: Path, seconds: float = 3.0, *, title: str | None = None, album: str | None = None,
             artist: str | None = None, track: str | None = None, genre: str | None = None,
             salt: int = 0) -> Path:
    """Erzeugt eine gültige, stille MP3 (MPEG-1 Layer III, 128 kbit/s, 44,1 kHz) – eigene Testdatei."""
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    frame = header + bytes([salt % 256]) + bytes(417 - 5)
    frames = int(seconds * 44100 / 1152)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame * frames)
    if any((title, album, artist, track, genre)):
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3

        ID3().save(str(path))
        tags = EasyID3(str(path))
        for k, v in {"title": title, "album": album, "artist": artist, "tracknumber": track, "genre": genre}.items():
            if v:
                tags[k] = v
        tags.save()
    return path


# ---------------------------------------------------------------- Fakes
class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def url_for(self, s3_key: str) -> str:
        self.calls.append(s3_key)
        return f"https://bucket.s3.eu-west-1.amazonaws.com/{s3_key}?X-Amz-Signature=sig{len(self.calls)}"


class FakeParams:
    def __init__(self, mode: Mode = Mode.NORMAL, key: str | None = "sk-test") -> None:
        self._mode, self._key = mode, key

    def mode(self) -> Mode:
        return self._mode

    def openai_api_key(self) -> str | None:
        return self._key

    def invalidate_api_key(self) -> None:
        self.invalidated = True


@dataclass
class FakeOpenAI:
    """Scriptbare Transport-Funktion für den OpenAI-Client."""

    replies: list[Any] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def text(self, text: str, *, inp: int = 900, out: int = 60) -> FakeOpenAI:
        self.replies.append((200, {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": inp, "output_tokens": out, "input_tokens_details": {"cached_tokens": 0}}}))
        return self

    def tool(self, book_id: str, text: str = "") -> FakeOpenAI:
        out: list[dict[str, Any]] = [{"type": "function_call", "name": "play_audiobook",
                                      "arguments": json.dumps({"book_id": book_id}), "call_id": "c1"}]
        if text:
            out.insert(0, {"type": "message", "content": [{"type": "output_text", "text": text}]})
        self.replies.append((200, {"status": "completed", "output": out, "usage": {"input_tokens": 1, "output_tokens": 1}}))
        return self

    def status(self, code: int, body: bytes = b"{}") -> FakeOpenAI:
        self.replies.append((code, body))
        return self

    def error(self, kind: str) -> FakeOpenAI:
        self.replies.append(LlmError(kind))
        return self

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        if not self.replies:
            raise LlmError("network")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        code, data = r
        return code, data if isinstance(data, bytes) else json.dumps(data).encode()


def book(book_id: str = "mord-im-kraeuterbeet", title: str = "Mord im Kräuterbeet", author: str = "Anna Gärtner",
         genres: tuple[str, ...] = ("gartenkrimi",), chapters: int = 3, dur_ms: int = 600_000,
         imported_at: str = "2026-10-01T10:00:00+00:00", series: str = "", series_no: float | None = None) -> Book:
    return Book(book_id=book_id, title=title, author=author, genres=genres, imported_at=imported_at,
                series=series, series_no=series_no,
                chapters=tuple(Chapter(index=i, title=f"Kapitel {i + 1}", s3_key=f"audiobooks/{book_id}/{i + 1:03d}.mp3",
                                       duration_ms=dur_ms, sha256=f"{book_id}-{i}") for i in range(chapters)))


@dataclass
class Harness:
    services: Services
    store: MemoryStore
    openai: FakeOpenAI
    signer: FakeSigner
    params: FakeParams
    progressive_calls: list[str]
    skill: Any = None

    def send(self, event: dict[str, Any]) -> dict[str, Any]:
        if self.skill is None:
            self.skill = build_skill(self.services)
        return handle_event(self.skill, event)


@pytest.fixture
def harness() -> Harness:
    return make_harness()


def make_harness(settings: Settings | None = None, clock: Callable[[], float] | None = None) -> Harness:
    settings = settings or Settings(progressive_after_s=5.0)
    store = MemoryStore()
    openai = FakeOpenAI()
    signer = FakeSigner()
    params = FakeParams()
    progressive: list[str] = []
    import time as _t

    services = Services(
        settings=settings, store=store, signer=signer, params=params,  # type: ignore[arg-type]
        llm_factory=lambda key: OpenAIClient(key, settings.openai_model, transport=openai),
        progressive=lambda hi, ssml: progressive.append(ssml),
        clock=clock or _t.monotonic,
    )
    return Harness(services, store, openai, signer, params, progressive)


# ---------------------------------------------------------------- Alexa-Requests
def envelope(request: dict[str, Any], *, session: dict[str, Any] | None = None, new: bool = False,
             audio: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {"System": {"application": {"applicationId": "amzn1.ask.skill.test"},
                                      "user": {"userId": USER}, "device": {"deviceId": DEVICE,
                                      "supportedInterfaces": {"AudioPlayer": {}}},
                                      "apiEndpoint": "https://api.eu.amazonalexa.com", "apiAccessToken": "tok"}}
    if audio is not None:
        ctx["AudioPlayer"] = audio
    env: dict[str, Any] = {"version": "1.0", "context": ctx,
                           "request": {"requestId": f"req-{uuid.uuid4()}", "timestamp": "2026-10-24T10:00:00Z",
                                       "locale": "de-DE", **request}}
    if session is not None or new:
        env["session"] = {"new": new, "sessionId": "sess-1", "application": {"applicationId": "amzn1.ask.skill.test"},
                          "user": {"userId": USER}, "attributes": session or {}}
    return env


def launch() -> dict[str, Any]:
    return envelope({"type": "LaunchRequest"}, new=True)


def intent(name: str, slots: dict[str, str] | None = None, *, session: dict[str, Any] | None = None,
           audio: dict[str, Any] | None = None, in_session: bool = True) -> dict[str, Any]:
    slot_data = {k: {"name": k, "value": v} for k, v in (slots or {}).items()}
    req = {"type": "IntentRequest", "intent": {"name": name, "confirmationStatus": "NONE", "slots": slot_data}}
    return envelope(req, session=(session or {}) if in_session else None, audio=audio)


def audio_event(kind: str, token: str, offset: int = 0, **extra: Any) -> dict[str, Any]:
    return envelope({"type": f"AudioPlayer.{kind}", "token": token, "offsetInMilliseconds": offset, **extra})


def speech(resp: dict[str, Any]) -> str:
    out = (resp.get("response") or {}).get("outputSpeech") or {}
    return out.get("ssml", "") or out.get("text", "")


def directives(resp: dict[str, Any]) -> list[dict[str, Any]]:
    return (resp.get("response") or {}).get("directives") or []


def ends_session(resp: dict[str, Any]) -> bool | None:
    return (resp.get("response") or {}).get("shouldEndSession")


def attrs(resp: dict[str, Any]) -> dict[str, Any]:
    return resp.get("sessionAttributes") or {}
