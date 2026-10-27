"""Gemeinsame Bausteine der Handler: Abhängigkeiten, Antworten, Fallback-Texte."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.interfaces.audioplayer import (
    AudioItem,
    AudioItemMetadata,
    PlayBehavior,
    PlayDirective,
    Stream,
)

from superkugel.audiobooks.hosting import UrlSigner
from superkugel.audiobooks.service import AudiobookService, PlayCommand
from superkugel.config import Settings
from superkugel.conversation.llm import OpenAIClient
from superkugel.services.logs import hash_user
from superkugel.services.ops import CircuitBreaker, ParameterSource
from superkugel.services.storage import Store
from superkugel.services.usage import UsageGuard
from superkugel.speech.ssml import to_ssml
from superkugel.speech.styles import SpeechStyle, get_style
from superkugel.speech.texts import text

ProgressiveSender = Callable[[HandlerInput, str], None]


@dataclass
class Services:
    settings: Settings
    store: Store
    signer: UrlSigner
    params: ParameterSource
    llm_factory: Callable[[str], OpenAIClient]
    progressive: ProgressiveSender
    clock: Callable[[], float] = time.monotonic
    _audio: AudiobookService | None = field(default=None, repr=False)
    media_client_factory: Callable[[str, str], Any] | None = None  # Podcast-Index-Client (Tests: Fake)
    reminder_transport: Any = None  # Tests: gefälschte Reminders-API (sonst urllib)
    now: Callable[[], dt.datetime] = field(default=lambda: dt.datetime.now(dt.UTC))  # Wanduhr (Tests: fest)

    @property
    def style(self) -> SpeechStyle:
        return get_style(self.settings.speech_style)

    @property
    def circuit(self) -> CircuitBreaker:
        return CircuitBreaker(self.store, self.settings)

    @property
    def usage(self) -> UsageGuard:
        return UsageGuard(self.store, self.settings)

    def audio(self) -> AudiobookService:
        # Pro Request neu, damit die Bibliothek nicht über Container-Lebenszeiten veraltet.
        return AudiobookService(self.store, self.signer, max_retries=self.settings.max_playback_retries)

    def say(self, text: str, slow: bool = False) -> str:
        return to_ssml(text, voice=self.settings.voice, rate=self.settings.speech_rate, slow=slow)

    def t(self, key: str, **kwargs: object) -> str:
        """Feste Ansage in der konfigurierten Anrede (du/Sie)."""
        return text(self.settings.address_form, key, **kwargs)

    def fallback_text(self) -> str:
        return self.t("fallback")

    def count(self, field_name: str, n: int = 1) -> None:
        """Tageszähler für den Wochenbericht (nie Inhalte)."""
        from superkugel.services import stats

        stats.count(self.store, self.settings, field_name, n, now=self.now())


def uid(handler_input: HandlerInput) -> str:
    system = handler_input.request_envelope.context.system
    raw = system.user.user_id if system and system.user else "anonymous"
    device = system.device.device_id if system and system.device else ""
    return hash_user(raw or "anonymous", device or "")


def slot(handler_input: HandlerInput, name: str) -> str:
    """Rohwert eines Slots (leer, wenn nicht gefüllt)."""
    req = handler_input.request_envelope.request
    slots = getattr(getattr(req, "intent", None), "slots", None) or {}
    s = slots.get(name)
    return str(s.value).strip() if s is not None and s.value else ""


def session_attrs(handler_input: HandlerInput) -> dict[str, Any]:
    return handler_input.attributes_manager.session_attributes


def has_session(handler_input: HandlerInput) -> bool:
    """Außerhalb einer Sitzung („Alexa, weiter“ beim Hören) gibt es keine Sitzungsattribute."""
    return handler_input.request_envelope.session is not None


def audio_context(handler_input: HandlerInput) -> tuple[str | None, int | None]:
    ctx = handler_input.request_envelope.context
    ap = getattr(ctx, "audio_player", None) if ctx else None
    if not ap:
        return None, None
    return ap.token, ap.offset_in_milliseconds


def end_with(services: Services, handler_input: HandlerInput, text: str) -> Response:
    """Spricht einen Satz und beendet die Sitzung sauber – danach hört Alexa wieder normal zu."""
    return handler_input.response_builder.speak(services.say(text)).set_should_end_session(True).response


def keep_open(services: Services, handler_input: HandlerInput, text: str, reprompt: str | None) -> Response:
    """Sitzung offen lassen. Ohne ``reprompt`` hört Alexa still zu (keine Nachfrage) und beendet
    die Sitzung leise, wenn nichts mehr kommt."""
    session_attrs(handler_input)["last_speech"] = text
    rb = handler_input.response_builder.speak(services.say(text))
    if reprompt:
        rb.ask(services.say(reprompt))
    return rb.set_should_end_session(False).response


def play_directive(cmd: PlayCommand) -> PlayDirective:
    chapter = cmd.book.chapters[cmd.chapter]
    return PlayDirective(
        play_behavior=PlayBehavior.ENQUEUE if cmd.behavior == "ENQUEUE" else PlayBehavior.REPLACE_ALL,
        audio_item=AudioItem(
            stream=Stream(
                token=cmd.token,
                url=cmd.url,
                offset_in_milliseconds=cmd.offset_ms,
                expected_previous_token=cmd.expected_previous_token,
            ),
            metadata=AudioItemMetadata(title=cmd.book.title, subtitle=chapter.title or f"Kapitel {cmd.chapter + 1}"),
        ),
    )
