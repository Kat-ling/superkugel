"""AudioPlayer- und PlaybackController-Ereignisse.

Auf AudioPlayer-Ereignisse darf ein Skill laut Alexa-Doku nur mit AudioPlayer-Direktiven
antworten (keine Sprache, keine Sitzung). Deshalb gibt hier jeder Pfad entweder eine
Direktive oder eine leere Antwort zurück – auch im Fehlerfall.
"""

from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.audiobooks import player
from superkugel.audiobooks.player import Position
from superkugel.handlers.common import Services, audio_context, play_directive, uid
from superkugel.services.logs import log
from superkugel.services.ops import Mode


def _req(hi: HandlerInput):
    return hi.request_envelope.request


def on_started(services: Services, hi: HandlerInput) -> Response:
    r = _req(hi)
    services.audio().on_started(uid(hi), r.token, int(r.offset_in_milliseconds or 0))
    return hi.response_builder.response


def on_stopped(services: Services, hi: HandlerInput) -> Response:
    r = _req(hi)
    services.audio().on_stopped(uid(hi), r.token, int(r.offset_in_milliseconds or 0))
    return hi.response_builder.response


def on_nearly_finished(services: Services, hi: HandlerInput) -> Response:
    cmd = services.audio().on_nearly_finished(uid(hi), _req(hi).token)
    if cmd:
        hi.response_builder.add_directive(play_directive(cmd))
    return hi.response_builder.response


def on_finished(services: Services, hi: HandlerInput) -> Response:
    services.audio().on_finished(uid(hi), _req(hi).token)
    return hi.response_builder.response


def on_failed(services: Services, hi: HandlerInput) -> Response:
    r = _req(hi)
    # request.token = der Stream, der fehlschlug (kann ein eingereihtes nächstes Kapitel sein).
    token = r.token
    state = getattr(r, "current_playback_state", None)
    offset: int | None = None
    if state and state.token == token and state.offset_in_milliseconds:
        offset = int(state.offset_in_milliseconds)
    err = getattr(getattr(r, "error", None), "object_type", None) or str(getattr(getattr(r, "error", None), "type", ""))
    cmd = services.audio().on_failed(uid(hi), token, offset, str(err))
    if cmd:
        hi.response_builder.add_directive(play_directive(cmd))
    return hi.response_builder.response


def on_controller(services: Services, hi: HandlerInput) -> Response:
    """Tasten am Gerät / in der App: Play, Pause, Nächstes, Vorheriges."""
    kind = hi.request_envelope.request.object_type
    audio = services.audio()
    user = uid(hi)
    token, offset = audio_context(hi)
    if kind == "PlaybackController.PauseCommandIssued":
        from ask_sdk_model.interfaces.audioplayer import StopDirective

        hi.response_builder.add_directive(StopDirective())  # zuerst: Pause muss immer wirken
        if token:
            try:
                audio.on_stopped(user, token, int(offset or 0))
            except Exception as exc:  # noqa: BLE001
                log("progress_save_failed", error=type(exc).__name__)
        return hi.response_builder.response
    if services.params.mode() is Mode.MAINTENANCE:
        return hi.response_builder.response
    found = audio.position_from_context(user, token, offset)
    if not found:
        return hi.response_builder.response
    book, pos = found
    if kind == "PlaybackController.NextCommandIssued":
        nxt = player.next_chapter(book, pos.chapter)
        if nxt is None:
            return hi.response_builder.response
        pos = Position(nxt, 0)
    elif kind == "PlaybackController.PreviousCommandIssued":
        pos = player.rewind(book, pos, services.settings.rewind_s)
    else:  # PlayCommandIssued
        pos = player.resume_position(book, pos.chapter, pos.offset_ms)
    return hi.response_builder.add_directive(play_directive(audio.command(user, book, pos))).response


def on_system_exception(services: Services, hi: HandlerInput) -> Response:
    err = getattr(hi.request_envelope.request, "error", None)
    log("system_exception", error_type=str(getattr(err, "object_type", "") or getattr(err, "type", "")))
    return hi.response_builder.response
