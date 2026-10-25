"""Skill-Aufbau und Lambda-Einstieg."""

from __future__ import annotations

import concurrent.futures as cf
import contextvars
import time
from collections.abc import Callable
from typing import Any

from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.utils import get_intent_name, is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.services.directive import Header, SendDirectiveRequest, SpeakDirective

from superkugel.audiobooks.hosting import S3UrlSigner
from superkugel.config import Settings
from superkugel.conversation.llm import OpenAIClient
from superkugel.handlers import audio, conversation, playback
from superkugel.handlers.common import Services, end_with
from superkugel.services.logs import hash_user, log, metric
from superkugel.services.ops import Mode, ParameterSource
from superkugel.services.storage import DynamoStore

Handler = Callable[[Services, HandlerInput], Response]

# Zeitpunkt, an dem Lambda die Anfrage erhalten hat (inkl. Kaltstart) – Basis des 8-s-Budgets
REQUEST_STARTED: contextvars.ContextVar[float | None] = contextvars.ContextVar("request_started", default=None)
_PROGRESSIVE_POOL = cf.ThreadPoolExecutor(max_workers=1)


class FnHandler(AbstractRequestHandler):
    """``guarded``: im Wartungsmodus nicht ausführen (Stopp/Pause/Ereignisse bleiben immer aktiv)."""

    def __init__(self, services: Services, can: Callable[[HandlerInput], bool], fn: Handler, guarded: bool) -> None:
        self.services, self.can, self.fn, self.guarded = services, can, fn, guarded

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return self.can(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        if self.guarded and self.services.params.mode() is Mode.MAINTENANCE:
            if str(handler_input.request_envelope.request.object_type).startswith("PlaybackController."):
                return handler_input.response_builder.response
            return end_with(self.services, handler_input, self.services.t("maintenance"))
        return self.fn(self.services, handler_input)


class SafetyNet(AbstractExceptionHandler):
    """Fängt jeden unerwarteten Fehler. Ergebnis: kurzer Hinweis, Sitzung endet, Alexa ist wieder frei."""

    def __init__(self, services: Services) -> None:
        self.services = services

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        req_type = getattr(handler_input.request_envelope.request, "object_type", "")
        log("unhandled_error", error=type(exception).__name__, request_type=req_type)
        metric("UnhandledError", 1)
        if req_type.startswith(("AudioPlayer.", "PlaybackController.", "System.", "SessionEndedRequest")):
            return handler_input.response_builder.response  # dort ist keine Sprache erlaubt
        return end_with(self.services, handler_input, self.services.fallback_text())


def _intent(*names: str) -> Callable[[HandlerInput], bool]:
    return lambda hi: any(is_intent_name(n)(hi) for n in names)


def _is_playing(hi: HandlerInput) -> bool:
    ctx = hi.request_envelope.context
    ap = getattr(ctx, "audio_player", None)
    activity = str(getattr(ap, "player_activity", "") or "")
    return bool(ap and ap.token and activity.endswith("PLAYING"))


def _stop(services: Services, hi: HandlerInput) -> Response:
    if _is_playing(hi):
        return audio.pause(services, hi)
    return conversation.handle_goodbye(services, hi)


def _session_ended(services: Services, hi: HandlerInput) -> Response:
    return hi.response_builder.response


def build_skill(services: Services) -> Any:
    sb = CustomSkillBuilder(api_client=DefaultApiClient())
    if services.settings.skill_id:
        sb.skill_id = services.settings.skill_id  # verwirft Anfragen fremder Skills

    def timed(fn: Callable[[Services, HandlerInput, float], Response]) -> Handler:
        def run(s: Services, hi: HandlerInput) -> Response:
            started = REQUEST_STARTED.get()
            return fn(s, hi, started if started is not None else s.clock())

        return run

    routes: list[tuple[Callable[[HandlerInput], bool], Handler]] = [
        (is_request_type("LaunchRequest"), conversation.handle_launch),
        # AudioPlayer-Ereignisse
        (is_request_type("AudioPlayer.PlaybackStarted"), playback.on_started),
        (is_request_type("AudioPlayer.PlaybackStopped"), playback.on_stopped),
        (is_request_type("AudioPlayer.PlaybackNearlyFinished"), playback.on_nearly_finished),
        (is_request_type("AudioPlayer.PlaybackFinished"), playback.on_finished),
        (is_request_type("AudioPlayer.PlaybackFailed"), playback.on_failed),
        (lambda hi: str(getattr(hi.request_envelope.request, "object_type", "")).startswith("PlaybackController."),
         playback.on_controller),
        (is_request_type("System.ExceptionEncountered"), playback.on_system_exception),
        (is_request_type("SessionEndedRequest"), _session_ended),
        # Hörbuch-Befehle
        (_intent("ResumeAudiobookIntent", "AMAZON.ResumeIntent"), audio.resume_current),
        (_intent("PlayAudiobookIntent"), timed(audio.play_title)),
        (_intent("PlayGenreIntent"), lambda s, hi: audio.play_genre(s, hi)),
        (_intent("PlayNewestIntent"), lambda s, hi: audio.play_genre(s, hi, newest=True)),
        (_intent("ListAudiobooksIntent"), audio.list_books),
        (_intent("AMAZON.PauseIntent"), audio.pause),
        (_intent("RewindIntent"), audio.rewind),
        (_intent("ForwardIntent"), audio.forward),
        (_intent("NextChapterIntent", "AMAZON.NextIntent"), audio.next_chapter),
        (_intent("AMAZON.PreviousIntent"), audio.previous),
        (_intent("PreviousChapterIntent"), audio.previous_chapter),
        (_intent("AMAZON.StartOverIntent"), audio.start_over),
        (_intent("WhatIsPlayingIntent"), audio.whats_playing),
        (_intent("AMAZON.LoopOnIntent", "AMAZON.LoopOffIntent", "AMAZON.ShuffleOnIntent",
                 "AMAZON.ShuffleOffIntent"), audio.unsupported),
        # Gespräch
        (conversation.can_chat, timed(conversation.handle_chat_intent)),
        (_intent("AMAZON.YesIntent"), timed(conversation.handle_yes)),
        (_intent("AMAZON.NoIntent"), timed(conversation.handle_no)),
        (_intent("StartChatIntent"), conversation.handle_start_chat),
        (_intent("AMAZON.RepeatIntent"), conversation.handle_repeat),
        (_intent("AMAZON.HelpIntent"), conversation.handle_help),
        (_intent("ForgetConversationIntent"), conversation.handle_forget),
        (_intent("AMAZON.StopIntent", "AMAZON.CancelIntent"), _stop),
        (_intent("AMAZON.NavigateHomeIntent"), lambda s, hi: hi.response_builder.set_should_end_session(True).response),
        (_intent("AMAZON.FallbackIntent"), conversation.handle_fallback),
        # Unbekannter Intent (z. B. nach Modelländerung): wie Fallback behandeln
        (is_request_type("IntentRequest"), conversation.handle_fallback),
    ]
    # Diese Routen laufen auch im Wartungsmodus: Audio-Ereignisse, Stopp/Pause, Sitzungsende.
    always = {playback.on_started, playback.on_stopped, playback.on_nearly_finished, playback.on_finished,
              playback.on_failed, playback.on_system_exception, playback.on_controller, audio.pause, _stop,
              _session_ended}
    for can, fn in routes:
        sb.add_request_handler(FnHandler(services, can, fn, guarded=fn not in always))
    sb.add_exception_handler(SafetyNet(services))
    return sb.create()


def send_progressive(hi: HandlerInput, ssml: str, timeout_s: float = 0.8) -> None:
    """Zwischenmeldung senden; nie länger als ``timeout_s`` warten (Aufruf hat sonst kein Timeout)."""
    req = hi.request_envelope.request
    directive = SendDirectiveRequest(header=Header(request_id=req.request_id), directive=SpeakDirective(speech=ssml))
    future = _PROGRESSIVE_POOL.submit(hi.service_client_factory.get_directive_service().enqueue, directive)
    try:
        future.result(timeout=timeout_s)
    except cf.TimeoutError:
        log("progressive_slow")


def default_services(settings: Settings | None = None) -> Services:
    settings = settings or Settings.from_env()
    store = DynamoStore(settings.table_name, settings.aws_region)
    signer = S3UrlSigner(settings.audio_bucket, settings.aws_region, settings.audio_url_expiry_s)
    return Services(
        settings=settings,
        store=store,
        signer=signer,
        params=ParameterSource(settings),
        llm_factory=lambda key: OpenAIClient(
            key, settings.openai_model, settings.openai_base_url,
            settings.openai_reasoning_effort, settings.max_output_tokens,
        ),
        progressive=send_progressive,
        clock=time.monotonic,
    )


_SKILL: Any = None


_EMERGENCY_SPEECH = ("<speak>Das klappt gerade leider nicht. Alexa funktioniert aber ganz normal weiter.</speak>")


def _emergency_response(req_type: str) -> dict[str, Any]:
    """Antwort, wenn selbst der Skill-Aufbau scheitert (ohne SDK)."""
    if req_type.startswith(("AudioPlayer.", "PlaybackController.", "System.", "SessionEndedRequest")):
        return {"version": "1.0", "response": {}}
    return {"version": "1.0", "response": {"outputSpeech": {"type": "SSML", "ssml": _EMERGENCY_SPEECH},
                                           "shouldEndSession": True}}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    global _SKILL
    started = time.monotonic()
    token = REQUEST_STARTED.set(started)
    req = (event.get("request") or {})
    system = (event.get("context") or {}).get("System") or {}
    user = (system.get("user") or {}).get("userId") or ""
    device = (system.get("device") or {}).get("deviceId") or ""
    try:
        if _SKILL is None:
            _SKILL = build_skill(default_services())
        return handle_event(_SKILL, event, context)
    except Exception as exc:  # noqa: BLE001 - letzte Verteidigungslinie
        log("fatal_error", error=type(exc).__name__)
        metric("UnhandledError", 1)
        return _emergency_response(str(req.get("type", "")))
    finally:
        REQUEST_STARTED.reset(token)
        intent = (req.get("intent") or {}).get("name", "")
        # user = pseudonyme Kennung (für superkugel_admin.py reset-progress --user-hash)
        log("request_done", request_type=req.get("type"), intent=intent, user_hash=hash_user(user, device) if user else "",
            ms=int((time.monotonic() - started) * 1000))


def _deserialize(event: dict[str, Any]) -> Any:
    import json

    from ask_sdk_core.serialize import DefaultSerializer
    from ask_sdk_model import RequestEnvelope

    return DefaultSerializer().deserialize(json.dumps(event), RequestEnvelope)


def handle_event(skill: Any, event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Event an einen Skill schicken und serialisierte Antwort zurückgeben."""
    from ask_sdk_core.serialize import DefaultSerializer

    response = skill.invoke(request_envelope=_deserialize(event), context=context)
    serialized: dict[str, Any] = DefaultSerializer().serialize(response)
    return serialized


__all__ = ["build_skill", "default_services", "get_intent_name", "handle_event", "lambda_handler"]
